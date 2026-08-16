"""Tmux window management tools (read and mutate)."""

import json

from tmux_mcp.core.errors import TmuxError, TmuxNotRunningError
from tmux_mcp.core.formats import get_window_format, make_sentinel, parse_line, unescape_tmux_value
from tmux_mcp.core.models import WindowModel
from tmux_mcp.core.runner import run_tmux


async def tmux_list_windows(target: str = "", all_sessions: bool = False) -> str:
    """List tmux windows for a session or across all sessions.

    Args:
        target: Session target ID or name (e.g. "$0" or "mysession"). Default empty lists current/all.
        all_sessions: If True, lists windows across all sessions (tmux list-windows -a).

    Returns:
        JSON array string of WindowModel objects.
    """
    sep = make_sentinel()
    args = ["list-windows", "-F", get_window_format(sep)]
    if all_sessions:
        args.append("-a")
    elif target:
        args.extend(["-t", target])

    try:
        raw = await run_tmux(args)
    except (TmuxNotRunningError, TmuxError) as e:
        if "no server running" in str(e) or "no sessions" in str(e) or "can't find" in str(e):
            return "[]"
        raise e

    windows: list[dict] = []
    for line in raw.splitlines():
        fields = parse_line(line, sep, expected_fields=6)
        if len(fields) >= 6:
            window = WindowModel(
                id=fields[0],
                index=int(fields[1]) if fields[1].isdigit() else 0,
                name=unescape_tmux_value(fields[2]),
                active=fields[3] == "1",
                panes_count=int(fields[4]) if fields[4].isdigit() else 0,
                session_id=fields[5],
            )
            windows.append(window.model_dump())

    return json.dumps(windows, indent=2)


async def tmux_create_window(
    target: str = "",
    name: str = "",
    start_directory: str = "",
    select: bool = True,
) -> str:
    """Create a new window in target session.

    Args:
        target: Target session ID or name (e.g. "$0").
        name: Name for the new window.
        start_directory: Starting working directory for new window.
        select: If True, select the newly created window (default True).

    Returns:
        JSON string of created WindowModel.
    """
    sep = make_sentinel()
    args = ["new-window", "-P", "-F", get_window_format(sep)]

    if not select:
        args.append("-d")
    if target:
        args.extend(["-t", target])
    if name:
        args.extend(["-n", name])
    if start_directory:
        args.extend(["-c", start_directory])

    raw = await run_tmux(args)
    fields = parse_line(raw.strip(), sep, expected_fields=6)
    if len(fields) >= 6:
        window = WindowModel(
            id=fields[0],
            index=int(fields[1]) if fields[1].isdigit() else 0,
            name=fields[2],
            active=fields[3] == "1",
            panes_count=int(fields[4]) if fields[4].isdigit() else 0,
            session_id=fields[5],
        )
        return json.dumps(window.model_dump(), indent=2)

    return json.dumps({"status": "created", "name": name})


async def tmux_rename_window(target: str = "", new_name: str = "") -> str:
    """Rename a tmux window.

    Args:
        target: Target window ID or name (e.g. "@0").
        new_name: New name for the window.

    Returns:
        JSON status response.
    """
    if not new_name:
        return json.dumps({"error": "new_name cannot be empty"})

    args = ["rename-window"]
    if target:
        args.extend(["-t", target])
    args.append(new_name)

    await run_tmux(args)
    return json.dumps({"status": "renamed", "new_name": new_name})


async def tmux_select_window(target: str = "") -> str:
    """Select target window to become active.

    Args:
        target: Target window ID or index/name (e.g. "@1").

    Returns:
        JSON status response.
    """
    if not target:
        return json.dumps({"error": "target window required"})

    await run_tmux(["select-window", "-t", target])
    return json.dumps({"status": "selected", "target": target})


async def tmux_move_window(
    target: str = "",
    to_session: str = "",
    to_index: int = -1,
) -> str:
    """Move a window to another index or session.

    Args:
        target: Source window ID or name (e.g. "@0").
        to_session: Target session ID/name (optional).
        to_index: Target window index number (optional, -1 for default).

    Returns:
        JSON status response.
    """
    args = ["move-window"]
    if target:
        args.extend(["-s", target])

    dst = ""
    if to_session:
        dst = to_session
        if to_index >= 0:
            dst += f":{to_index}"
    elif to_index >= 0:
        dst = str(to_index)

    if dst:
        args.extend(["-t", dst])

    await run_tmux(args)
    return json.dumps({"status": "moved", "target": target, "destination": dst})


async def tmux_kill_window(target: str = "") -> str:
    """Kill a specified tmux window (destructive action).

    Args:
        target: Target window ID or index/name (e.g. "@1").

    Returns:
        JSON status response.
    """
    if not target:
        return json.dumps({"error": "target window ID required"})

    await run_tmux(["kill-window", "-t", target])
    return json.dumps({"status": "killed", "target": target})
