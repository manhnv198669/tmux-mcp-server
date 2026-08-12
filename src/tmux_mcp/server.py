"""MCPServer setup and tool registration with profile validation."""

import logging
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from tmux_mcp.config import Config, get_config, set_config
from tmux_mcp.tools.execution import (
    tmux_cancel_command,
    tmux_get_command_result,
    tmux_list_commands,
    tmux_run_command,
    tmux_wait_command,
)
from tmux_mcp.tools.inspect import (
    tmux_display_message,
    tmux_list_clients,
    tmux_server_info,
    tmux_show_options,
)
from tmux_mcp.tools.layout import (
    tmux_break_pane,
    tmux_kill_pane,
    tmux_move_pane,
    tmux_resize_pane,
    tmux_select_pane,
    tmux_set_layout,
    tmux_split_pane,
    tmux_swap_panes,
    tmux_zoom_pane,
)
from tmux_mcp.tools.panes import (
    tmux_clear_pane,
    tmux_get_pane_info,
    tmux_list_panes,
    tmux_read_pane,
    tmux_search_pane,
    tmux_send_keys,
    tmux_send_special_key,
)
from tmux_mcp.tools.sessions import (
    tmux_create_session,
    tmux_get_session,
    tmux_kill_session,
    tmux_list_sessions,
    tmux_rename_session,
    tmux_switch_client,
)
from tmux_mcp.tools.windows import (
    tmux_create_window,
    tmux_kill_window,
    tmux_list_windows,
    tmux_move_window,
    tmux_rename_window,
    tmux_select_window,
)

logger = logging.getLogger(__name__)

STANDARD_PROFILE_TOOLS = {
    "list_sessions",
    "get_session",
    "create_session",
    "list_windows",
    "create_window",
    "select_window",
    "list_panes",
    "get_pane_info",
    "read_pane",
    "search_pane",
    "send_keys",
    "send_special_key",
    "split_pane",
    "select_pane",
    "resize_pane",
    "zoom_pane",
    "run_command",
    "get_command_result",
    "wait_command",
    "list_commands",
    "server_info",
    "list_clients",
}


def create_server(config: Config | None = None) -> MCPServer:
    """Create and configure the MCPServer instance."""
    if config is not None:
        set_config(config)
    cfg = get_config()

    app = MCPServer(
        name="tmux-mcp",
        title="tmux MCP Server",
        description="MCP server exposing tmux command-line operations cleanly and securely.",
        version="0.1.0",
    )

    read_only_annot = ToolAnnotations(readOnlyHint=True, idempotentHint=True)
    mutating_annot = ToolAnnotations(readOnlyHint=False, idempotentHint=False)
    destructive_annot = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False)

    # All 37 tools definition map: (name, func, description, annotations, is_mutating, is_destructive)
    all_tools_map = [
        # 4.1 Sessions (6)
        ("list_sessions", tmux_list_sessions, "List active tmux sessions with details", read_only_annot, False, False),
        ("get_session", tmux_get_session, "Get detailed info for a specific session by ID or name", read_only_annot, False, False),
        ("create_session", tmux_create_session, "Create a new detached tmux session", mutating_annot, True, False),
        ("rename_session", tmux_rename_session, "Rename a tmux session", mutating_annot, True, False),
        ("switch_client", tmux_switch_client, "Switch attached client to another session", mutating_annot, True, False),
        ("kill_session", tmux_kill_session, "Kill a specified tmux session", destructive_annot, True, True),

        # 4.2 Windows (6)
        ("list_windows", tmux_list_windows, "List tmux windows for a session or across all sessions", read_only_annot, False, False),
        ("create_window", tmux_create_window, "Create a new window in target session", mutating_annot, True, False),
        ("rename_window", tmux_rename_window, "Rename a tmux window", mutating_annot, True, False),
        ("select_window", tmux_select_window, "Select target window to become active", mutating_annot, True, False),
        ("move_window", tmux_move_window, "Move a window to another index or session", mutating_annot, True, False),
        ("kill_window", tmux_kill_window, "Kill a specified tmux window", destructive_annot, True, True),

        # 4.3 Panes (Read & Interact - 7)
        ("list_panes", tmux_list_panes, "List tmux panes for a target window/session or all sessions", read_only_annot, False, False),
        ("get_pane_info", tmux_get_pane_info, "Get status, command, path, and dimensions of a pane", read_only_annot, False, False),
        ("read_pane", tmux_read_pane, "Read visible text and scrollback history from a pane", read_only_annot, False, False),
        ("search_pane", tmux_search_pane, "Search pane scrollback history using regex pattern", read_only_annot, False, False),
        ("send_keys", tmux_send_keys, "Send literal string text to a target pane", mutating_annot, True, False),
        ("send_special_key", tmux_send_special_key, "Send a special key shortcut (e.g. Enter, Up, C-c)", mutating_annot, True, False),
        ("clear_pane", tmux_clear_pane, "Clear pane terminal screen and/or scrollback buffer", mutating_annot, True, False),

        # 4.4 Panes (Layout & Arrangement - 9)
        ("split_pane", tmux_split_pane, "Split target pane horizontally or vertically", mutating_annot, True, False),
        ("select_pane", tmux_select_pane, "Select active pane by ID or direction (L, R, U, D)", mutating_annot, True, False),
        ("resize_pane", tmux_resize_pane, "Resize pane relative or to absolute dimensions", mutating_annot, True, False),
        ("zoom_pane", tmux_zoom_pane, "Toggle zoom state (maximize/restore) for target pane", mutating_annot, True, False),
        ("swap_panes", tmux_swap_panes, "Swap positions of two panes", mutating_annot, True, False),
        ("move_pane", tmux_move_pane, "Move/join a pane into another window or pane layout", mutating_annot, True, False),
        ("break_pane", tmux_break_pane, "Break a pane out into its own new window", mutating_annot, True, False),
        ("set_layout", tmux_set_layout, "Set pane layout preset (tiled, even-horizontal, etc.)", mutating_annot, True, False),
        ("kill_pane", tmux_kill_pane, "Kill a specified tmux pane", destructive_annot, True, True),

        # 4.5 Execution (5)
        ("run_command", tmux_run_command, "Run shell command with exact exit code and pipe-pane output capture", mutating_annot, True, False),
        ("get_command_result", tmux_get_command_result, "Poll status or fetch result of a tracked command execution", read_only_annot, False, False),
        ("wait_command", tmux_wait_command, "Wait for a running command execution to finish", read_only_annot, False, False),
        ("list_commands", tmux_list_commands, "List tracked command executions in current session", read_only_annot, False, False),
        ("cancel_command", tmux_cancel_command, "Cancel running command execution by sending C-c signal", mutating_annot, True, False),

        # 4.6 Server & Inspect (4)
        ("server_info", tmux_server_info, "Get tmux server version, socket info, and counts", read_only_annot, False, False),
        ("list_clients", tmux_list_clients, "List connected tmux clients", read_only_annot, False, False),
        ("display_message", tmux_display_message, "Display a message on tmux status bar", mutating_annot, True, False),
        ("show_options", tmux_show_options, "Show options for tmux server, session, or window", read_only_annot, False, False),
    ]

    all_tool_names = {t[0] for t in all_tools_map}
    profile = cfg.tool_profile.strip().lower()

    # Validate profile name / typos (Issue #6)
    if profile not in ("read", "standard", "full", ""):
        explicit_list = [t.strip() for t in profile.split(",")]
        unknown = set(explicit_list) - all_tool_names
        if unknown:
            raise ValueError(f"Invalid tool profile or unknown tool name(s) in --tools: {unknown}")

    for name, func, desc, annot, is_mutating, is_destructive in all_tools_map:
        if cfg.read_only and is_mutating:
            continue

        if profile == "read" and is_mutating:
            continue
        elif profile == "standard" and name not in STANDARD_PROFILE_TOOLS:
            continue
        elif profile in ("full", ""):
            pass
        elif "," in profile or (profile not in ("read", "standard", "full")):
            allowed_names = [t.strip() for t in profile.split(",")]
            if name not in allowed_names:
                continue

        app.tool(
            name=name,
            description=desc,
            annotations=annot,
        )(func)

    return app
