"""Test parsing names with colons ':', octal string sequences, backslashes, spaces, and special characters."""

import json

import pytest

from tmux_mcp.core.runner import run_tmux
from tmux_mcp.tools.sessions import tmux_create_session, tmux_list_sessions
from tmux_mcp.tools.windows import tmux_create_window, tmux_list_windows


@pytest.mark.asyncio
async def test_parsing_colon_in_window_name(tmux_server):
    # Create window with colon in name: "12:30"
    window_name = "12:30"
    await run_tmux(["new-window", "-n", window_name])

    windows_json = await tmux_list_windows()
    windows = json.loads(windows_json)

    names = [w["name"] for w in windows]
    assert window_name in names, f"Expected '{window_name}' in windows, got {names}"


@pytest.mark.asyncio
async def test_parsing_octal_sequence_in_session_name(tmux_server):
    # Create session with octal escape string in name: "evil\\037INJECTED"
    evil_name = r"evil\037INJECTED"
    await run_tmux(["new-session", "-d", "-s", evil_name])

    sessions_json = await tmux_list_sessions()
    sessions = json.loads(sessions_json)

    matched = [s for s in sessions if "evil" in s["name"] and "INJECTED" in s["name"]]
    assert len(matched) == 1, f"Expected clean match for '{evil_name}', got {sessions}"
    assert matched[0]["windows_count"] == 1
    assert isinstance(matched[0]["created_ts"], int)


@pytest.mark.asyncio
async def test_parsing_backslash_in_names(tmux_server):
    # Lỗi B: Create session 's\\test' and window 'w\\test', assert read back as exact string
    sess_name = r"s\test"
    win_name = r"w\test"

    await tmux_create_session(name=sess_name)
    await tmux_create_window(name=win_name)

    sessions_json = await tmux_list_sessions()
    sessions = json.loads(sessions_json)
    sess_names = [s["name"] for s in sessions]
    assert sess_name in sess_names, f"Expected '{sess_name}' in sessions, got {sess_names}"

    windows_json = await tmux_list_windows()
    windows = json.loads(windows_json)
    win_names = [w["name"] for w in windows]
    assert win_name in win_names, f"Expected '{win_name}' in windows, got {win_names}"
