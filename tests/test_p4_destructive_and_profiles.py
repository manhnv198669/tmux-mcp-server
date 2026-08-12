"""Tests for Phase 4 (destructive tools, read-only mode, and tool profiles)."""

import json
import pytest

from tmux_mcp.config import Config
from tmux_mcp.server import create_server
from tmux_mcp.tools.layout import tmux_kill_pane, tmux_split_pane
from tmux_mcp.tools.sessions import tmux_create_session, tmux_kill_session, tmux_list_sessions
from tmux_mcp.tools.windows import tmux_create_window, tmux_kill_window, tmux_list_windows


@pytest.mark.asyncio
async def test_destructive_operations(tmux_server):
    # 1. Create a session to kill
    await tmux_create_session(name="sess_to_kill")
    kill_s_res = await tmux_kill_session("sess_to_kill")
    assert json.loads(kill_s_res)["status"] == "killed"

    # 2. Create window to kill
    win_json = await tmux_create_window(name="win_to_kill")
    win_id = json.loads(win_json)["id"]
    kill_w_res = await tmux_kill_window(win_id)
    assert json.loads(kill_w_res)["status"] == "killed"

    # 3. Split pane and kill created pane
    split_json = await tmux_split_pane(direction="vertical")
    pane_id = json.loads(split_json)["id"]
    kill_p_res = await tmux_kill_pane(pane_id)
    assert json.loads(kill_p_res)["status"] == "killed"


@pytest.mark.asyncio
async def test_read_only_mode():
    cfg = Config(read_only=True, tool_profile="full")
    app = create_server(cfg)
    tools = await app.list_tools()
    tool_names = [t.name for t in tools]

    assert "list_sessions" in tool_names
    assert "create_session" not in tool_names
    assert "run_command" not in tool_names
    assert "kill_session" not in tool_names


@pytest.mark.asyncio
async def test_tool_profiles_counts():
    # Profile: full -> 37 tools
    app_full = create_server(Config(tool_profile="full"))
    tools_full = await app_full.list_tools()
    assert len(tools_full) == 37, f"Expected 37 tools in 'full' profile, got {len(tools_full)}"

    # Profile: standard -> 22 tools (R6 context optimization)
    app_std = create_server(Config(tool_profile="standard"))
    tools_std = await app_std.list_tools()
    assert len(tools_std) == 22, f"Expected 22 tools in 'standard' profile, got {len(tools_std)}"

    # Profile: read -> 13 read-only tools
    app_read = create_server(Config(tool_profile="read"))
    tools_read = await app_read.list_tools()
    assert len(tools_read) == 13, f"Expected 13 tools in 'read' profile, got {len(tools_read)}"


@pytest.mark.asyncio
async def test_invalid_profile_typo_raises_error():
    # Typo profile name should raise ValueError instead of silently registering 0 tools (Issue #6)
    with pytest.raises(ValueError, match="Invalid tool profile"):
        create_server(Config(tool_profile="standrd_typo"))
