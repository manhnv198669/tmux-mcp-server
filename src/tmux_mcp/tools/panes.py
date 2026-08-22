"""Tmux pane management tools (read and interact)."""

import json
import re

from tmux_mcp.core.ansi import strip_ansi
from tmux_mcp.core.errors import TmuxError, TmuxNotRunningError
from tmux_mcp.core.formats import get_pane_format, make_sentinel, parse_line, unescape_tmux_value
from tmux_mcp.core.guard import assert_pane_writable
from tmux_mcp.core.models import PaneModel
from tmux_mcp.core.prefix import resolve_prefix
from tmux_mcp.core.runner import run_tmux

NAMED_KEYS = frozenset({
    "up", "down", "left", "right", "enter", "escape", "tab", "space", "bspace", "btab",
    "delete", "dc", "ic", "insert", "home", "end", "pageup", "pagedown", "npage", "ppage",
    # tmux only knows F1..F12; an unknown name like "F13" is silently typed into the
    # pane as literal text instead of being sent as a key, so it must not validate.
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
})


def validate_key(key: str) -> str:
    """Validate a key specification.

    Accepts an optional chain of modifiers C-, M-, S- (case-insensitive, any order,
    each at most once), followed by EITHER a single printable ASCII character OR
    one of NAMED_KEYS (case-insensitive).

    Returns the key unchanged when valid; raises ValueError with a clear message otherwise.
    """
    if not key or not key.strip():
        raise ValueError("key cannot be empty or whitespace")

    if len(key) > 32:
        raise ValueError(f"key too long ({len(key)} chars), max 32")

    key = key.strip()

    if " " in key:
        raise ValueError(f"key cannot contain spaces: '{key}'")

    modifiers = {"c", "m", "s"}
    seen_modifiers = set()
    parts = key.split("-")
    key_part = parts[-1].lower()

    for part in parts[:-1]:
        part_lower = part.lower()
        if part_lower not in modifiers:
            raise ValueError(f"invalid modifier '{part}'; must be C-, M-, or S-")
        if part_lower in seen_modifiers:
            raise ValueError(f"duplicate modifier '{part}'")
        seen_modifiers.add(part_lower)

    if len(key_part) == 1:
        if ord(key_part) < 32 or ord(key_part) > 126:
            raise ValueError(f"invalid printable character: '{key_part}'")
    elif key_part not in NAMED_KEYS:
        raise ValueError(f"unknown key name: '{key_part}' (must be a printable char or named key)")

    return key


async def tmux_send_special_key(
    target: str = "",
    key: str = "Enter",
    repeat: int = 1,
    exit_copy_mode: bool = False,
    prefix_override: str = "",
) -> str:
    """Send a special keyboard shortcut or arrow key to a pane.

    Refuses if the pane is in copy-mode, where navigation keys would scroll a human
    viewer's screen instead of reaching the application.

    Args:
        target: Target pane ID (e.g. "%0").
        key: Special key name (e.g. Up, Down, C-c, Enter, Escape, Tab, Prefix).
             Use "Prefix" to send the tmux server's configured prefix key dynamically.
        repeat: Number of times to repeat keypress (default 1).
        exit_copy_mode: If True, cancel an active copy-mode before sending instead of
            refusing.
        prefix_override: When key is "Prefix", send this key instead of resolving the
            local tmux server's prefix. Use this when the pane holds a NESTED or REMOTE
            tmux (e.g. over ssh), where the prefix that matters belongs to that inner
            server, which the local server cannot see. Keys sent with send-keys bypass
            the local server's key table and are received by the tmux one level down
            (nested/remote), so a single prefix is enough to reach it.

    Returns:
        JSON status message.
    """
    if key.lower() == "prefix":
        if prefix_override:
            key = validate_key(prefix_override)
        else:
            key = await resolve_prefix()
    else:
        validate_key(key)

    await assert_pane_writable(target, exit_copy_mode=exit_copy_mode)

    args = ["send-keys"]
    if target:
        args.extend(["-t", target])
    if repeat > 1:
        args.extend(["-N", str(repeat)])
    args.append(key)

    await run_tmux(args)
    return json.dumps({"status": "sent_special", "target": target, "key": key, "repeat": repeat})


def _parse_pane_model(fields: list[str]) -> PaneModel | None:
    if len(fields) < 13:
        return None
    return PaneModel(
        alternate_on=len(fields) > 13 and fields[13] == "1",
        in_mode=len(fields) > 14 and fields[14] == "1",
        id=fields[0],
        index=int(fields[1]) if fields[1].isdigit() else 0,
        active=fields[2] == "1",
        width=int(fields[3]) if fields[3].isdigit() else 0,
        height=int(fields[4]) if fields[4].isdigit() else 0,
        current_command=unescape_tmux_value(fields[5]),
        current_path=unescape_tmux_value(fields[6]),
        pid=int(fields[7]) if fields[7].isdigit() else 0,
        history_size=int(fields[8]) if fields[8].isdigit() else 0,
        dead=fields[9] == "1",
        zoomed=fields[10] == "1",
        window_id=fields[11],
        session_id=fields[12],
    )


async def tmux_list_panes(target: str = "", all_panes: bool = False) -> str:
    """List tmux panes for a target window/session or across all sessions.

    Args:
        target: Target window or session ID/name (e.g. "@0" or "$0").
        all_panes: If True, lists all panes across all sessions (tmux list-panes -a).

    Returns:
        JSON array string of PaneModel objects.
    """
    sep = make_sentinel()
    args = ["list-panes", "-F", get_pane_format(sep)]
    if all_panes:
        args.append("-a")
    elif target:
        args.extend(["-t", target])

    try:
        raw = await run_tmux(args)
    except (TmuxNotRunningError, TmuxError) as e:
        if "no server running" in str(e) or "can't find" in str(e):
            return "[]"
        raise e

    panes: list[dict] = []
    for line in raw.splitlines():
        fields = parse_line(line, sep, expected_fields=15)
        model = _parse_pane_model(fields)
        if model:
            panes.append(model.model_dump())

    return json.dumps(panes, indent=2)


async def tmux_get_pane_info(target: str = "") -> str:
    """Get detailed status and properties of a specific pane.

    Args:
        target: Target pane ID or specifier (e.g. "%0"). Default active pane.

    Returns:
        JSON string of PaneModel object, or "{}" if not found.
    """
    sep = make_sentinel()
    args = ["list-panes", "-F", get_pane_format(sep)]
    if target:
        args.extend(["-t", target])

    try:
        raw = await run_tmux(args)
    except (TmuxNotRunningError, TmuxError) as e:
        if "no server running" in str(e) or "can't find" in str(e):
            return "{}"
        raise e

    for line in raw.splitlines():
        fields = parse_line(line, sep, expected_fields=15)
        model = _parse_pane_model(fields)
        if model:
            if target and target.startswith("%"):
                if model.id == target:
                    return json.dumps(model.model_dump(), indent=2)
            else:
                return json.dumps(model.model_dump(), indent=2)

    return "{}"


async def tmux_read_pane(
    target: str = "",
    lines: int = 200,
    full_history: bool = False,
    include_colors: bool = False,
    start: int = 0,
    end: int = 0,
    join_wrapped: bool = False,
) -> str:
    """Read visible text and scrollback history from a target pane.

    Always includes history_size and truncated flag so the caller knows if content was truncated.

    When the pane is running a full-screen app (vim, htop, less, a nested tmux),
    tmux keeps no reachable scrollback for it: only the visible screen exists. That
    case is reported as scrollback_available=false plus a warning, and `truncated`
    is set whenever history was asked for but could not be delivered.

    Args:
        target: Target pane ID (e.g. "%0"). Default active pane.
        lines: Number of recent lines to capture from bottom (default: 200).
        full_history: If True, capture entire scrollback history (-S -).
        include_colors: If True, keep ANSI color escape sequences.
        start: Starting line index for range capture (optional, e.g. -500).
        end: Ending line index for range capture (optional).
        join_wrapped: If True, rejoin lines the terminal wrapped at pane width, so a
            long value split across two rows comes back as one string (capture-pane -J).

    Returns:
        JSON string: { pane_id, history_size, lines_returned, truncated,
                       scrollback_available, alternate_on, text, warning? }
    """
    info_json = await tmux_get_pane_info(target)
    info = json.loads(info_json)
    pane_id = info.get("id", target or "%0")
    history_size = info.get("history_size", 0)
    alternate_on = bool(info.get("alternate_on", False))

    args = ["capture-pane", "-p", "-t", pane_id]

    if include_colors:
        args.append("-e")
    if join_wrapped:
        args.append("-J")

    if full_history:
        args.extend(["-S", "-"])
    elif start != 0 or end != 0:
        if start != 0:
            args.extend(["-S", str(start)])
        if end != 0:
            args.extend(["-E", str(end)])
    elif lines > 0:
        args.extend(["-S", f"-{lines}"])

    try:
        raw_text = await run_tmux(args)
    except (TmuxNotRunningError, TmuxError) as e:
        return json.dumps(
            {
                "pane_id": pane_id,
                "history_size": 0,
                "lines_returned": 0,
                "truncated": False,
                "scrollback_available": not alternate_on,
                "alternate_on": alternate_on,
                "text": "",
                "error": str(e),
            },
            indent=2,
        )

    if not include_colors:
        raw_text = strip_ansi(raw_text)

    output_lines = raw_text.splitlines()
    returned_count = len(output_lines)

    history_requested = full_history or start != 0 or (lines > 0 and not (start or end))

    if alternate_on:
        # tmux parks the pane's history while the alternate screen is up, so
        # history_size reads as ~1 and the usual comparison would claim nothing was
        # missed. Anything older than the visible screen is simply unreachable here.
        truncated = history_requested
    else:
        truncated = not full_history and (lines > 0) and (history_size > lines)

    result = {
        "pane_id": pane_id,
        "history_size": history_size,
        "lines_returned": returned_count,
        "truncated": truncated,
        "scrollback_available": not alternate_on,
        "alternate_on": alternate_on,
        "text": raw_text,
    }

    if alternate_on:
        result["warning"] = (
            "Pane is on the alternate screen (full-screen app such as vim, htop, less "
            "or a nested tmux), so only the visible screen was returned and no "
            "scrollback exists to read. lines/full_history/start/end had no effect. "
            "To reach earlier output, read the underlying log file instead."
        )

    return json.dumps(result, indent=2)


async def tmux_search_pane(
    target: str = "",
    pattern: str = "",
    max_results: int = 50,
) -> str:
    """Search pane scrollback history using regex pattern.

    Args:
        target: Target pane ID (e.g. "%0"). Default active pane.
        pattern: Regex pattern to search for in scrollback history.
        max_results: Maximum matching lines to return (default: 50).

    Returns:
        JSON string: { pane_id, total_matches, searched_lines, scrollback_available,
                       matches: [{ line_no, text }], warning? }
    """
    if not pattern:
        return json.dumps({"pane_id": target, "total_matches": 0, "matches": []})

    read_res = await tmux_read_pane(target=target, full_history=True)
    data = json.loads(read_res)
    text = data.get("text", "")
    pane_id = data.get("pane_id", target)
    scrollback_available = data.get("scrollback_available", True)

    lines = text.splitlines()
    regex = re.compile(pattern)

    matches: list[dict] = []
    for idx, line in enumerate(lines, start=1):
        if regex.search(line):
            matches.append({"line_no": idx, "text": line})
            if len(matches) >= max_results:
                break

    result = {
        "pane_id": pane_id,
        "total_matches": len(matches),
        "searched_lines": len(lines),
        "scrollback_available": scrollback_available,
        "matches": matches,
    }

    if not scrollback_available:
        # Without this the caller reads "0 matches" as "not in this pane's history",
        # when in fact only the visible screen was ever searched.
        result["warning"] = (
            f"Only the {len(lines)} visible lines were searched: the pane is on the "
            "alternate screen (full-screen app or nested tmux) and has no reachable "
            "scrollback. A zero result does NOT mean the pattern never appeared."
        )

    return json.dumps(result, indent=2)


async def tmux_send_keys(
    target: str = "",
    keys: str = "",
    enter: bool = False,
    exit_copy_mode: bool = False,
) -> str:
    """Send literal string text to a target pane.

    Uses send-keys -l -- to safely send literal text without interpreting key names.

    Refuses if the pane is in copy-mode: tmux would feed the keys to the mode's key
    table, execute a truncated fragment of them in the shell, and silently drop the
    rest.

    Args:
        target: Target pane ID (e.g. "%0").
        keys: Literal text content to send.
        enter: If True, sends Enter key after text payload (default False).
        exit_copy_mode: If True, cancel an active copy-mode before typing instead of
            refusing. This yanks a human viewer's screen back to the live output.

    Returns:
        JSON status message.
    """
    if not keys and not enter:
        return json.dumps({"status": "no_op"})

    await assert_pane_writable(target, exit_copy_mode=exit_copy_mode)

    if keys:
        args = ["send-keys"]
        if target:
            args.extend(["-t", target])
        args.extend(["-l", "--", keys])
        await run_tmux(args)

    if enter:
        args_enter = ["send-keys"]
        if target:
            args_enter.extend(["-t", target])
        args_enter.append("Enter")
        await run_tmux(args_enter)

    return json.dumps({"status": "sent", "target": target, "keys": keys, "enter": enter})


async def tmux_clear_pane(
    target: str = "",
    clear_history: bool = True,
) -> str:
    """Clear pane terminal screen and/or scrollback history buffer.

    Args:
        target: Target pane ID (e.g. "%0").
        clear_history: If True, clears scrollback buffer (clear-history).

    Returns:
        JSON status message.
    """
    # Reset the terminal state directly (-R) instead of sending C-l to the shell.
    # send-keys only queues the key: tmux returns before the shell has processed
    # it, so a clear-history issued right after would be undone when the shell
    # finally redraws and pushes the old screen back into the scrollback.
    args_keys = ["send-keys"]
    if target:
        args_keys.extend(["-t", target])
    args_keys.append("-R")
    await run_tmux(args_keys)

    if clear_history:
        args_hist = ["clear-history"]
        if target:
            args_hist.extend(["-t", target])
        await run_tmux(args_hist)

    return json.dumps({"status": "cleared", "target": target, "clear_history": clear_history})
