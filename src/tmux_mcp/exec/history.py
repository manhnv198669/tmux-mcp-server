"""Append-only audit log of every command this server runs.

The shell's own history is the wrong place to record them. It belongs to the human:
it is what a prefix search walks through, and burying their work under generated
lines makes their terminal worse. It also cannot hold what an audit actually needs
-- no exit code, no timestamp, no pane, no duration.

So the server keeps its own record and leaves the interactive history alone. One
line per event, tab-separated, in the order things happened:

    2026-08-17T00:12:03+0700  RUN  cmd_a92195b6cea9  %12  -  -      /repo  uv run pytest
    2026-08-17T00:12:05+0700  OK   cmd_a92195b6cea9  %12  0  1.42s  /repo  uv run pytest

    ts  event  command_id  pane  exit  elapsed  cwd  command

Dispatch is logged before the command finishes, so `tail -f` shows work in flight
rather than only completed work. Events are RUN, OK, FAIL and CANCEL, which makes
`grep FAIL` a useful question to ask of the file.
"""

import logging
import os
import time

from tmux_mcp.config import get_config
from tmux_mcp.core.models import CommandRunModel

logger = logging.getLogger(__name__)

SEP = "\t"

# Terminal statuses mapped to a column value worth grepping for.
_EVENT_BY_STATUS = {
    "completed": "OK",
    "failed": "FAIL",
    "cancelled": "CANCEL",
}

_write_failure_logged = False


def _sanitize(value: str) -> str:
    """Keep one record on one line, so a field can never forge a column."""
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _stamp(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts))


def _append(line: str) -> None:
    """Write one record. A failure here must never break the command itself."""
    global _write_failure_logged

    cfg = get_config()
    if not cfg.save_commands_history or not cfg.commands_history_file:
        return

    path = cfg.commands_history_file
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # O_NOFOLLOW because the default path lives in a world-writable /tmp, where
        # a symlink planted under that name would otherwise redirect the log --
        # and these lines carry every command and working directory of the session.
        # O_APPEND keeps concurrent writes from interleaving mid-line.
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.write(fd, line.encode("utf-8", errors="replace"))
        finally:
            os.close(fd)
    except OSError as e:
        # Logged once: a broken path would otherwise repeat this on every command.
        if not _write_failure_logged:
            _write_failure_logged = True
            logger.warning("command history not being written to %s: %s", path, e)


def _record(
    event: str,
    model: CommandRunModel,
    cwd: str,
    exit_col: str,
    elapsed: str,
    pane: str = "",
) -> None:
    fields = [
        _stamp(time.time()),
        event,
        model.command_id,
        # The resolved %id where available: model.pane_id holds whatever string the
        # caller used, and a session name can be reused by a later session.
        pane or model.pane_id or "-",
        exit_col,
        elapsed,
        _sanitize(cwd) or "-",
        _sanitize(model.command),
    ]
    _append(SEP.join(fields) + "\n")


def record_started(model: CommandRunModel, cwd: str = "", pane: str = "") -> None:
    """Log a command at dispatch, while it is still running."""
    _record("RUN", model, cwd, exit_col="-", elapsed="-", pane=pane)


def record_finished(model: CommandRunModel, cwd: str = "", pane: str = "") -> None:
    """Log a command once it reaches a terminal state."""
    event = _EVENT_BY_STATUS.get(model.status, "END")
    elapsed = "-"
    if model.created_at:
        elapsed = f"{max(0.0, time.time() - model.created_at):.2f}s"
    exit_col = "-" if model.exit_code < 0 else str(model.exit_code)
    _record(event, model, cwd, exit_col=exit_col, elapsed=elapsed, pane=pane)
