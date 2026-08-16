"""Per-target write protection.

`--read-only` is all-or-nothing: it removes every mutating tool from the server.
This module is the fine-grained version -- specific sessions/windows/panes stay
readable but reject every write, while the rest of the server stays fully usable.

A target is matched by *identity*, not by the literal string the caller passed:
"%88", "skinstrading:3.0" and "skinstrading:3" can all name the same pane, so the
target is resolved through tmux first and every name it answers to is tested.
"""

import fnmatch
import logging

from tmux_mcp.config import get_config
from tmux_mcp.core.errors import (
    PaneInModeError,
    ProtectedTargetError,
    TmuxError,
    TmuxNotRunningError,
)
from tmux_mcp.core.formats import make_sentinel, parse_line
from tmux_mcp.core.runner import run_tmux

logger = logging.getLogger(__name__)


async def assert_pane_writable(target: str, exit_copy_mode: bool = False) -> None:
    """Refuse to type into a pane that is in copy-mode, or leave the mode first.

    copy-mode is a property of the pane, not of a client: tmux offers no way to give
    one viewer a scrolled-back view while another writes. So a pane being viewed and
    a pane being typed into are mutually exclusive states, and the only honest
    choices are to refuse or to cancel the viewer's mode explicitly.
    """
    sep = make_sentinel()
    args = ["display-message", "-p"]
    if target:
        args.extend(["-t", target])
    args.append(sep.join(["#{pane_in_mode}", "#{pane_mode}", "#{pane_id}"]))

    try:
        raw = await run_tmux(args)
    except (TmuxError, TmuxNotRunningError):
        # Target does not resolve; the real command will report that itself.
        return

    fields = parse_line(raw.strip(), sep, expected_fields=3)
    if len(fields) < 3 or fields[0] != "1":
        return

    mode = fields[1] or "copy-mode"
    pane_id = fields[2] or target

    if not exit_copy_mode:
        raise PaneInModeError(pane_id, mode)

    logger.info("leaving %s on pane %s before writing (exit_copy_mode)", mode, pane_id)
    cancel_args = ["send-keys"]
    if target:
        cancel_args.extend(["-t", target])
    cancel_args.extend(["-X", "cancel"])
    await run_tmux(cancel_args)


async def resolve_identities(target: str) -> list[str]:
    """Return every name the given target answers to.

    An empty target is not skipped: it means "whatever pane tmux currently
    considers active", which is exactly the case a protection rule must catch.
    """
    sep = make_sentinel()
    fmt = sep.join(
        [
            "#{session_name}",
            "#{window_index}",
            "#{window_name}",
            "#{pane_index}",
            "#{pane_id}",
            "#{window_id}",
            "#{session_id}",
        ]
    )

    args = ["display-message", "-p"]
    if target:
        args.extend(["-t", target])
    args.append(fmt)

    raw = await run_tmux(args)
    fields = parse_line(raw.strip(), sep, expected_fields=7)
    if len(fields) < 7:
        return []

    sess, widx, wname, pidx, pane_id, window_id, session_id = fields[:7]
    return [
        sess,
        f"{sess}:{widx}",
        f"{sess}:{wname}",
        f"{sess}:{widx}.{pidx}",
        f"{sess}:{wname}.{pidx}",
        pane_id,
        window_id,
        session_id,
    ]


async def assert_target_allowed(target: str) -> None:
    """Raise ProtectedTargetError if `target` resolves onto a protected pattern."""
    patterns = get_config().protected_targets
    if not patterns:
        return

    try:
        identities = await resolve_identities(target)
    except (TmuxError, TmuxNotRunningError):
        # The target does not exist or the server is down; the real tmux command is
        # about to fail on its own with a clearer message. Nothing exists to protect.
        logger.debug("protection: could not resolve target %r, letting the call through", target)
        return

    for identity in identities:
        if not identity:
            continue
        for pattern in patterns:
            if fnmatch.fnmatch(identity, pattern):
                logger.warning(
                    "protection: refused write to %r (identity %r matches %r)",
                    target or "<current pane>",
                    identity,
                    pattern,
                )
                raise ProtectedTargetError(target, identity, pattern)


def parse_patterns(raw_values: list[str] | None) -> tuple[str, ...]:
    """Flatten repeated CLI flags and comma-separated values into a pattern tuple."""
    if not raw_values:
        return ()
    patterns: list[str] = []
    for value in raw_values:
        for part in value.split(","):
            part = part.strip()
            if part:
                patterns.append(part)
    return tuple(patterns)
