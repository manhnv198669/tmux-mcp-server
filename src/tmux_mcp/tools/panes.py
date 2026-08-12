"""Tmux pane management tools (read and interact)."""

import json
import re
from typing import Literal

from tmux_mcp.core.ansi import strip_ansi
from tmux_mcp.core.formats import get_pane_format, make_sentinel, parse_line, unescape_tmux_value
from tmux_mcp.core.models import PaneModel
from tmux_mcp.core.runner import run_tmux
from tmux_mcp.core.errors import TmuxError, TmuxNotRunningError

SpecialKeyType = Literal[
    "Up",
    "Down",
    "Left",
    "Right",
    "Enter",
    "Escape",
    "Tab",
    "Space",
    "BSpace",
    "Delete",
    "Home",
    "End",
    "PageUp",
    "PageDown",
    "F1",
    "F2",
    "F3",
    "F4",
    "F5",
    "F6",
    "F7",
    "F8",
    "F9",
    "F10",
    "F11",
    "F12",
    "C-c",
    "C-d",
    "C-z",
    "C-l",
    "C-a",
    "C-e",
]


def _parse_pane_model(fields: list[str]) -> PaneModel | None:
    if len(fields) < 13:
        return None
    return PaneModel(
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
        fields = parse_line(line, sep, expected_fields=13)
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
        fields = parse_line(line, sep, expected_fields=13)
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
) -> str:
    """Read visible text and scrollback history from a target pane.

    Always includes history_size and truncated flag so the caller knows if content was truncated.

    Args:
        target: Target pane ID (e.g. "%0"). Default active pane.
        lines: Number of recent lines to capture from bottom (default: 200).
        full_history: If True, capture entire scrollback history (-S -).
        include_colors: If True, keep ANSI color escape sequences.
        start: Starting line index for range capture (optional, e.g. -500).
        end: Ending line index for range capture (optional).

    Returns:
        JSON string: { pane_id, history_size, lines_returned, truncated, text }
    """
    info_json = await tmux_get_pane_info(target)
    info = json.loads(info_json)
    pane_id = info.get("id", target or "%0")
    history_size = info.get("history_size", 0)

    args = ["capture-pane", "-p", "-t", pane_id]

    if include_colors:
        args.append("-e")

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
                "text": "",
                "error": str(e),
            },
            indent=2,
        )

    if not include_colors:
        raw_text = strip_ansi(raw_text)

    output_lines = raw_text.splitlines()
    returned_count = len(output_lines)

    # Output is truncated if history is larger than requested lines
    truncated = not full_history and (lines > 0) and (history_size > lines)

    return json.dumps(
        {
            "pane_id": pane_id,
            "history_size": history_size,
            "lines_returned": returned_count,
            "truncated": truncated,
            "text": raw_text,
        },
        indent=2,
    )


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
        JSON string: { pane_id, total_matches, matches: [{ line_no, text }] }
    """
    if not pattern:
        return json.dumps({"pane_id": target, "total_matches": 0, "matches": []})

    read_res = await tmux_read_pane(target=target, full_history=True)
    data = json.loads(read_res)
    text = data.get("text", "")
    pane_id = data.get("pane_id", target)

    lines = text.splitlines()
    regex = re.compile(pattern)

    matches: list[dict] = []
    for idx, line in enumerate(lines, start=1):
        if regex.search(line):
            matches.append({"line_no": idx, "text": line})
            if len(matches) >= max_results:
                break

    return json.dumps(
        {
            "pane_id": pane_id,
            "total_matches": len(matches),
            "matches": matches,
        },
        indent=2,
    )


async def tmux_send_keys(
    target: str = "",
    keys: str = "",
    enter: bool = False,
) -> str:
    """Send literal string text to a target pane.

    Uses send-keys -l -- to safely send literal text without interpreting key names.

    Args:
        target: Target pane ID (e.g. "%0").
        keys: Literal text content to send.
        enter: If True, sends Enter key after text payload (default False).

    Returns:
        JSON status message.
    """
    if not keys and not enter:
        return json.dumps({"status": "no_op"})

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


async def tmux_send_special_key(
    target: str = "",
    key: SpecialKeyType = "Enter",
    repeat: int = 1,
) -> str:
    """Send a special keyboard shortcut or arrow key to a pane.

    Args:
        target: Target pane ID (e.g. "%0").
        key: Special key name (e.g. Up, Down, C-c, Enter, Escape, Tab).
        repeat: Number of times to repeat keypress (default 1).

    Returns:
        JSON status message.
    """
    args = ["send-keys"]
    if target:
        args.extend(["-t", target])
    if repeat > 1:
        args.extend(["-N", str(repeat)])
    args.append(key)

    await run_tmux(args)
    return json.dumps({"status": "sent_special", "target": target, "key": key, "repeat": repeat})


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
