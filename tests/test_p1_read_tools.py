"""Tests for Phase 1 read-only tools."""

import json

import pytest

from tmux_mcp.tools.inspect import tmux_server_info, tmux_show_options
from tmux_mcp.tools.panes import (
    tmux_get_pane_info,
    tmux_list_panes,
    tmux_read_pane,
    tmux_search_pane,
)
from tmux_mcp.tools.sessions import tmux_get_session, tmux_list_sessions
from tmux_mcp.tools.windows import tmux_list_windows


@pytest.mark.asyncio
async def test_read_tools_pipeline(tmux_server):
    # 1. Test sessions
    sessions_json = await tmux_list_sessions()
    sessions = json.loads(sessions_json)
    assert len(sessions) == 1
    session_id = sessions[0]["id"]
    session_name = sessions[0]["name"]

    get_sess_json = await tmux_get_session(session_name)
    get_sess = json.loads(get_sess_json)
    assert get_sess["id"] == session_id

    # 2. Test windows
    windows_json = await tmux_list_windows(session_name)
    windows = json.loads(windows_json)
    assert len(windows) >= 1
    window_id = windows[0]["id"]

    # 3. Test panes
    panes_json = await tmux_list_panes(window_id)
    panes = json.loads(panes_json)
    assert len(panes) >= 1
    pane_id = panes[0]["id"]

    pane_info_json = await tmux_get_pane_info(pane_id)
    pane_info = json.loads(pane_info_json)
    assert pane_info["id"] == pane_id

    # 4. Test read pane
    read_json = await tmux_read_pane(pane_id)
    read_res = json.loads(read_json)
    assert read_res["pane_id"] == pane_id
    assert "truncated" in read_res
    assert "text" in read_res

    # 5. Test search pane
    search_json = await tmux_search_pane(pane_id, pattern=".*")
    search_res = json.loads(search_json)
    assert "matches" in search_res

    # 6. Test server info
    srv_json = await tmux_server_info()
    srv = json.loads(srv_json)
    assert srv["running"] is True

    # 7. Test show options
    opt_json = await tmux_show_options(global_options=True)
    opt = json.loads(opt_json)
    assert isinstance(opt, dict)
