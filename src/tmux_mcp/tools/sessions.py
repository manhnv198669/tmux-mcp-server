"""Tmux session management tools (read and mutate)."""

import json

from tmux_mcp.core.errors import TmuxError, TmuxNotRunningError
from tmux_mcp.core.formats import get_session_format, make_sentinel, parse_line
from tmux_mcp.core.models import SessionModel
from tmux_mcp.core.runner import run_tmux


async def tmux_list_sessions(target: str = "") -> str:
    """List all active tmux sessions with details.

    Args:
        target: Optional session filter name or pattern (default empty for all sessions).

    Returns:
        JSON array string of SessionModel objects.
    """
    sep = make_sentinel()
    args = ["list-sessions", "-F", get_session_format(sep)]
    if target:
        args.extend(["-t", target])

    try:
        raw = await run_tmux(args)
    except (TmuxNotRunningError, TmuxError) as e:
        if "no server running" in str(e) or "no sessions" in str(e):
            return "[]"
        raise e

    sessions: list[dict] = []
    for line in raw.splitlines():
        fields = parse_line(line, sep, expected_fields=7)
        if len(fields) >= 7:
            session = SessionModel(
                id=fields[0],
                name=fields[1].replace("\\\\", "\\"),
                attached=fields[2] == "1",
                windows_count=int(fields[3]) if fields[3].isdigit() else 0,
                created_ts=int(fields[4]) if fields[4].isdigit() else 0,
                width=int(fields[5]) if fields[5].isdigit() else 0,
                height=int(fields[6]) if fields[6].isdigit() else 0,
            )
            sessions.append(session.model_dump())

    return json.dumps(sessions, indent=2)


async def tmux_get_session(target: str = "") -> str:
    """Get detailed information about a specific tmux session.

    Args:
        target: Session target ID or name (e.g. "$0" or "my-session"). Defaults to current/first session.

    Returns:
        JSON string of SessionModel, or empty object "{}" if not found.
    """
    sep = make_sentinel()
    args = ["list-sessions", "-F", get_session_format(sep)]
    if target:
        args.extend(["-f", f"#{{==:#{{session_name}},{target}}}"])

    try:
        raw = await run_tmux(args)
    except (TmuxNotRunningError, TmuxError) as e:
        if "no server running" in str(e) or "no sessions" in str(e) or "can't find session" in str(e):
            return "{}"
        raise e

    for line in raw.splitlines():
        fields = parse_line(line, sep, expected_fields=7)
        if len(fields) >= 7:
            session = SessionModel(
                id=fields[0],
                name=fields[1].replace("\\\\", "\\"),
                attached=fields[2] == "1",
                windows_count=int(fields[3]) if fields[3].isdigit() else 0,
                created_ts=int(fields[4]) if fields[4].isdigit() else 0,
                width=int(fields[5]) if fields[5].isdigit() else 0,
                height=int(fields[6]) if fields[6].isdigit() else 0,
            )
            return json.dumps(session.model_dump(), indent=2)

    return "{}"


async def tmux_create_session(
    name: str = "",
    start_directory: str = "",
    width: int = 0,
    height: int = 0,
) -> str:
    """Create a new detached tmux session.

    Requested width/height are enforced, not merely suggested: the default
    `window-size latest` makes tmux resize a detached window to whatever client is
    newest on the server, silently discarding -x/-y. This pins the window instead,
    which matters for driving TUIs -- an app rendered at 320 columns costs several
    times more to read back than the same screen at 120.

    Args:
        name: Name for the new session (optional, tmux auto-names if empty).
        start_directory: Starting directory path for initial window.
        width: Optional initial session width in columns.
        height: Optional initial session height in lines.

    Returns:
        JSON string of newly created SessionModel.
    """
    sep = make_sentinel()
    args = ["new-session", "-d", "-P", "-F", get_session_format(sep)]

    if name:
        args.extend(["-s", name])
    if start_directory:
        args.extend(["-c", start_directory])

    fixed_size = width > 0 and height > 0
    if fixed_size:
        args.extend(["-x", str(width), "-y", str(height)])

    raw = await run_tmux(args)
    fields = parse_line(raw.strip(), sep, expected_fields=7)
    if len(fields) < 7:
        return json.dumps({"status": "created", "name": name})

    session_id = fields[0]

    if fixed_size:
        await run_tmux(["set-option", "-w", "-t", session_id, "window-size", "manual"])
        await run_tmux(["resize-window", "-t", session_id, "-x", str(width), "-y", str(height)])

    # session_width/session_height render empty for a detached session, so the real
    # dimensions have to come from the window itself.
    actual_w, actual_h = 0, 0
    try:
        size_sep = make_sentinel()
        size_raw = await run_tmux(
            [
                "display-message",
                "-p",
                "-t",
                session_id,
                size_sep.join(["#{window_width}", "#{window_height}"]),
            ]
        )
        size_fields = parse_line(size_raw.strip(), size_sep, expected_fields=2)
        if len(size_fields) >= 2:
            actual_w = int(size_fields[0]) if size_fields[0].isdigit() else 0
            actual_h = int(size_fields[1]) if size_fields[1].isdigit() else 0
    except (TmuxNotRunningError, TmuxError):
        pass

    session = SessionModel(
        id=session_id,
        name=fields[1],
        attached=fields[2] == "1",
        windows_count=int(fields[3]) if fields[3].isdigit() else 0,
        created_ts=int(fields[4]) if fields[4].isdigit() else 0,
        width=actual_w or (int(fields[5]) if fields[5].isdigit() else 0),
        height=actual_h or (int(fields[6]) if fields[6].isdigit() else 0),
    )
    return json.dumps(session.model_dump(), indent=2)


async def tmux_rename_session(target: str = "", new_name: str = "") -> str:
    """Rename a tmux session.

    Args:
        target: Target session ID or current name.
        new_name: New name for the session.

    Returns:
        JSON string of updated SessionModel.
    """
    if not new_name:
        return json.dumps({"error": "new_name cannot be empty"})

    args = ["rename-session"]
    if target:
        args.extend(["-t", target])
    args.append(new_name)

    await run_tmux(args)
    return await tmux_get_session(new_name)


async def tmux_switch_client(target: str = "", session_name: str = "") -> str:
    """Switch attached tmux client to another session.

    Args:
        target: Target client TTY or empty for current client.
        session_name: Target session name to switch to.

    Returns:
        JSON status message.
    """
    if not session_name:
        return json.dumps({"error": "session_name cannot be empty"})

    args = ["switch-client", "-t", session_name]
    if target:
        args.extend(["-c", target])

    try:
        await run_tmux(args)
    except (TmuxNotRunningError, TmuxError) as e:
        return json.dumps({"error": str(e)})

    return json.dumps({"status": "switched", "target_session": session_name})


async def tmux_kill_session(target: str = "") -> str:
    """Kill a specified tmux session (destructive action).

    Args:
        target: Target session ID or name (e.g. "$0" or "mysession").

    Returns:
        JSON status message.
    """
    if not target:
        return json.dumps({"error": "target session ID or name required"})

    await run_tmux(["kill-session", "-t", target])
    return json.dumps({"status": "killed", "target": target})
