"""Test P0 functionality (tmux_list_sessions)."""

import json

import pytest

from tmux_mcp.tools.sessions import tmux_list_sessions


@pytest.mark.asyncio
async def test_tmux_list_sessions(tmux_server):
    res_str = await tmux_list_sessions()
    sessions = json.loads(res_str)

    assert isinstance(sessions, list)
    assert len(sessions) == 1
    assert sessions[0]["name"] == "test_session_0"
    assert sessions[0]["windows_count"] >= 1
