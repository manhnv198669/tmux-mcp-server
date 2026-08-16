"""Tests for Phase 2 mutating tools."""

import json

import pytest

from tmux_mcp.tools.layout import (
    tmux_set_layout,
    tmux_split_pane,
    tmux_zoom_pane,
)
from tmux_mcp.tools.panes import (
    tmux_read_pane,
    tmux_send_keys,
    tmux_send_special_key,
)
from tmux_mcp.tools.sessions import tmux_create_session, tmux_rename_session
from tmux_mcp.tools.windows import tmux_create_window, tmux_rename_window


@pytest.mark.asyncio
async def test_session_mutations(tmux_server):
    # 1. Create session
    new_sess_json = await tmux_create_session(name="sess_p2_test")
    new_sess = json.loads(new_sess_json)
    assert new_sess["name"] == "sess_p2_test"

    # 2. Rename session
    ren_json = await tmux_rename_session(target="sess_p2_test", new_name="sess_p2_renamed")
    ren_sess = json.loads(ren_json)
    assert ren_sess["name"] == "sess_p2_renamed"


@pytest.mark.asyncio
async def test_window_mutations(tmux_server):
    # 1. Create window
    win_json = await tmux_create_window(name="win_p2_test")
    win = json.loads(win_json)
    assert win["name"] == "win_p2_test"

    # 2. Rename window
    ren_json = await tmux_rename_window(target=win["id"], new_name="win_p2_renamed")
    ren_res = json.loads(ren_json)
    assert ren_res["status"] == "renamed"


@pytest.mark.asyncio
async def test_pane_layout_and_keys(tmux_server):
    # 1. Split pane
    split_json = await tmux_split_pane(direction="vertical", size=50)
    new_pane = json.loads(split_json)
    assert "id" in new_pane
    import asyncio
    await asyncio.sleep(0.3)

    # 2. Send keys to pane
    send_json = await tmux_send_keys(target="%0", keys="echo hello_tmux_p2", enter=True)
    send_res = json.loads(send_json)
    assert send_res["status"] == "sent"

    # 3. Read pane to verify output
    import asyncio
    await asyncio.sleep(0.3)
    read_json = await tmux_read_pane(target="%0", lines=50)
    read_res = json.loads(read_json)
    assert "hello_tmux_p2" in read_res["text"]

    # 4. Special key
    sk_json = await tmux_send_special_key(target=new_pane["id"], key="Enter")
    assert json.loads(sk_json)["status"] == "sent_special"

    # 5. Zoom toggle
    zoom_json = await tmux_zoom_pane(target=new_pane["id"])
    assert json.loads(zoom_json)["status"] == "zoomed_toggled"

    # 6. Set layout
    lay_json = await tmux_set_layout(layout="tiled")
    assert json.loads(lay_json)["status"] == "layout_set"
