"""Tmux server inspection and options tools (read-only)."""

import json
import logging

from tmux_mcp.core.errors import TmuxError, TmuxNotRunningError
from tmux_mcp.core.formats import parse_line
from tmux_mcp.core.runner import get_socket_args, run_tmux, run_tmux_batch

logger = logging.getLogger(__name__)


async def tmux_server_info() -> str:
    """Get general status of tmux server using batch runner (version, socket, session count, client count).

    Returns:
        JSON string containing server status info.
    """
    version = "unknown"
    running = True
    session_count = 0
    client_count = 0

    try:
        # Use display-message -p #{version} instead of -V so commands can be batched cleanly
        batch_results = await run_tmux_batch(
            [
                ["display-message", "-p", "#{version}"],
                ["list-sessions", "-F", "#{session_id}"],
                ["list-clients", "-F", "#{client_tty}"],
            ]
        )

        ver_raw = batch_results[0]
        if ver_raw:
            version = ver_raw.strip()

        sess_raw = batch_results[1]
        session_count = len([line for line in sess_raw.splitlines() if line.strip()])

        cli_raw = batch_results[2]
        client_count = len([line for line in cli_raw.splitlines() if line.strip()])
    except (TmuxNotRunningError, TmuxError) as e:
        logger.debug("Server not running or tmux command error: %s", e)
        running = False

    socket_info = "default"
    sock_args = get_socket_args()
    if sock_args:
        socket_info = " ".join(sock_args)

    return json.dumps(
        {
            "version": version,
            "running": running,
            "socket": socket_info,
            "session_count": session_count,
            "client_count": client_count,
        },
        indent=2,
    )


async def tmux_list_clients() -> str:
    """List connected tmux clients (TTY, attached session, size, activity).

    Returns:
        JSON array string of client objects.
    """
    fmt = "\x1f".join(
        [
            "#{client_tty}",
            "#{client_session}",
            "#{client_width}",
            "#{client_height}",
            "#{client_activity}",
        ]
    )

    try:
        raw = await run_tmux(["list-clients", "-F", fmt])
    except (TmuxNotRunningError, TmuxError):
        return "[]"

    clients: list[dict] = []
    for line in raw.splitlines():
        fields = parse_line(line, expected_fields=5)
        if len(fields) >= 5:
            clients.append(
                {
                    "tty": fields[0],
                    "session_name": fields[1],
                    "width": int(fields[2]) if fields[2].isdigit() else 0,
                    "height": int(fields[3]) if fields[3].isdigit() else 0,
                    "activity_ts": int(fields[4]) if fields[4].isdigit() else 0,
                }
            )

    return json.dumps(clients, indent=2)


async def tmux_display_message(target: str = "", message: str = "") -> str:
    """Display a status message on tmux status bar or echo pane info.

    Args:
        target: Target client or pane specifier (optional).
        message: Text message string to display.

    Returns:
        JSON status message.
    """
    if not message:
        return json.dumps({"error": "message text required"})

    args = ["display-message"]
    if target:
        args.extend(["-t", target])
    args.extend(["--", message])

    await run_tmux(args)
    return json.dumps({"status": "displayed", "target": target, "message": message})


async def tmux_show_options(
    target: str = "",
    global_options: bool = False,
    server_options: bool = False,
) -> str:
    """Show options for tmux server, session, or window.

    Args:
        target: Target session or window ID/name (optional).
        global_options: If True, show global options (-g).
        server_options: If True, show server options (-s).

    Returns:
        JSON dictionary string of option key-value pairs.
    """
    args = ["show-options"]
    if server_options:
        args.append("-s")
    elif global_options:
        args.append("-g")

    if target:
        args.extend(["-t", target])

    try:
        raw = await run_tmux(args)
    except (TmuxNotRunningError, TmuxError) as e:
        return json.dumps({"error": str(e)})

    options: dict[str, str] = {}
    for line in raw.splitlines():
        if " " in line:
            key, val = line.split(" ", maxsplit=1)
            options[key] = val.strip('"')
        else:
            options[line.strip()] = ""

    return json.dumps(options, indent=2)
