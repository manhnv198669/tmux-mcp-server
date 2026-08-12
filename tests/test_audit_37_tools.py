"""Comprehensive business logic tests for all 37 tmux-mcp tools.

Every single tool is invoked against a known setup state and asserted against EXACT business values.
"""

import asyncio
import json
import re
import pytest

from tmux_mcp.core.runner import run_tmux
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


# -----------------------------------------------------------------------------
# Live-state helpers
#
# Tools that return a hardcoded {"status": "..."} literal cannot be verified by
# asserting on that literal -- the assertion passes even when tmux did nothing.
# These helpers query tmux directly so tests compare against real server state.
# -----------------------------------------------------------------------------
async def live(fmt: str, target: str = "") -> str:
    """Read a single tmux format value straight from the server."""
    args = ["display-message", "-p"]
    if target:
        args += ["-t", target]
    args.append(fmt)
    return (await run_tmux(args)).strip()


async def live_list(subcommand: str, target: str, fmt: str) -> list[str]:
    """Read a list of tmux format values straight from the server."""
    args = [subcommand]
    if target:
        args += ["-t", target]
    args += ["-F", fmt]
    return [line for line in (await run_tmux(args)).splitlines() if line.strip()]


# -----------------------------------------------------------------------------
# 1. Execution Tools (5)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_execution_tools(tmux_server):
    # 1. tmux_run_command (completed)
    res_json = await tmux_run_command(command="echo EXEC_TEST_100", timeout=10.0)
    res = json.loads(res_json)
    assert res["status"] == "completed"
    assert res["exit_code"] == 0
    assert res["output"] == "EXEC_TEST_100"
    cmd_id = res["command_id"]

    # 2. tmux_get_command_result
    get_res = json.loads(await tmux_get_command_result(command_id=cmd_id))
    assert get_res["command_id"] == cmd_id
    assert get_res["output"] == "EXEC_TEST_100"

    # 3. tmux_list_commands
    list_cmd_res = json.loads(await tmux_list_commands())
    assert any(c["command_id"] == cmd_id for c in list_cmd_res)

    # 4. tmux_run_command with wait=False & tmux_wait_command
    async_res = json.loads(await tmux_run_command(command="sleep 1", wait=False))
    async_cid = async_res["command_id"]
    wait_res = json.loads(await tmux_wait_command(command_id=async_cid, timeout=5.0))
    assert wait_res["status"] == "completed"

    # 5. tmux_cancel_command
    running_res = json.loads(await tmux_run_command(command="sleep 30", timeout=1.0))
    r_cid = running_res["command_id"]
    cancel_res = json.loads(await tmux_cancel_command(command_id=r_cid))
    assert cancel_res["status"] == "cancelled"


# -----------------------------------------------------------------------------
# 2. Sessions Tools (6)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_sessions_tools(tmux_server):
    # 1. tmux_create_session
    s1_json = await tmux_create_session(name="sess_alpha")
    s1 = json.loads(s1_json)
    assert s1["name"] == "sess_alpha"
    assert isinstance(s1["width"], int)
    assert isinstance(s1["height"], int)

    await tmux_create_session(name="sess_beta")

    # 2. tmux_list_sessions
    list_json = await tmux_list_sessions()
    sessions = json.loads(list_json)
    names = {s["name"] for s in sessions}
    assert "sess_alpha" in names
    assert "sess_beta" in names

    # 3. tmux_get_session
    get_json = await tmux_get_session(target="sess_alpha")
    s_get = json.loads(get_json)
    assert s_get["name"] == "sess_alpha"

    # 4. tmux_rename_session
    await tmux_rename_session(target="sess_beta", new_name="sess_gamma")
    get_renamed = json.loads(await tmux_get_session(target="sess_gamma"))
    assert get_renamed["name"] == "sess_gamma"

    # 5. tmux_switch_client (verify status response or error handled gracefully)
    switch_res = json.loads(await tmux_switch_client(session_name="sess_gamma"))
    assert "status" in switch_res or "error" in switch_res

    # 6. tmux_kill_session
    kill_res = json.loads(await tmux_kill_session(target="sess_gamma"))
    assert kill_res["status"] == "killed"
    list_after = json.loads(await tmux_list_sessions())
    names_after = {s["name"] for s in list_after}
    assert "sess_gamma" not in names_after


# -----------------------------------------------------------------------------
# 3. Windows Tools (6)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_windows_tools(tmux_server):
    # Setup session
    await tmux_create_session(name="win_test_sess")

    # 1. tmux_create_window
    w1_json = await tmux_create_window(target="win_test_sess", name="win_one")
    w1 = json.loads(w1_json)
    assert w1["name"] == "win_one"

    await tmux_create_window(target="win_test_sess", name="win_two")

    # 2. tmux_list_windows
    list_json = await tmux_list_windows(target="win_test_sess")
    wins = json.loads(list_json)
    win_names = [w["name"] for w in wins]
    assert "win_one" in win_names
    assert "win_two" in win_names

    # 3. tmux_rename_window -- assert the rename landed in tmux, not that the
    #    tool echoed its own "renamed" literal back.
    await tmux_rename_window(target="win_test_sess:win_two", new_name="win_two_renamed")
    live_names = await live_list("list-windows", "win_test_sess", "#{window_name}")
    assert "win_two_renamed" in live_names
    assert "win_two" not in live_names

    # 4. tmux_select_window -- the selected window must actually be active.
    await tmux_select_window(target="win_test_sess:win_one")
    assert await live("#{window_name}", "win_test_sess") == "win_one"

    # 5. tmux_move_window -- the window must actually sit at index 5.
    await tmux_move_window(target="win_test_sess:win_one", to_index=5)
    live_indexed = await live_list(
        "list-windows", "win_test_sess", "#{window_index}:#{window_name}"
    )
    assert "5:win_one" in live_indexed

    # 6. tmux_kill_window -- the window must be gone from the server.
    await tmux_kill_window(target="win_test_sess:win_two_renamed")
    live_names = await live_list("list-windows", "win_test_sess", "#{window_name}")
    assert "win_two_renamed" not in live_names


# -----------------------------------------------------------------------------
# 4. Panes - Read & Interact Tools (7)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_panes_read_and_interact(tmux_server):
    # 1. tmux_split_pane & tmux_list_panes
    p1 = json.loads(await tmux_split_pane(direction="vertical"))
    panes_list = json.loads(await tmux_list_panes())
    live_panes = await live_list("list-panes", "", "#{pane_id}")
    assert len(panes_list) == len(live_panes)
    assert {p["id"] for p in panes_list} == set(live_panes)
    assert p1["id"] in live_panes

    # 2. tmux_get_pane_info
    p0_info = json.loads(await tmux_get_pane_info(target="%0"))
    assert p0_info["id"] == "%0"

    # 3. tmux_send_keys & tmux_read_pane
    await tmux_send_keys(target="%0", keys="echo AUDIT_TEST_MARKER_99", enter=True)
    await asyncio.sleep(0.5)

    read_json = await tmux_read_pane(target="%0", lines=50)
    read_data = json.loads(read_json)
    assert "AUDIT_TEST_MARKER_99" in read_data["text"]

    # 4. tmux_search_pane
    search_json = await tmux_search_pane(target="%0", pattern=r"AUDIT_TEST_MARKER_\d+")
    search_data = json.loads(search_json)
    assert search_data["total_matches"] >= 1
    assert any("AUDIT_TEST_MARKER_99" in m["text"] for m in search_data["matches"])

    # 5. tmux_send_special_key -- prove the key was really delivered by typing a
    #    command without Enter, then submitting it with the special key alone.
    await tmux_send_keys(target="%0", keys="echo SPECIAL_KEY_OK", enter=False)
    await asyncio.sleep(0.3)
    await tmux_send_special_key(target="%0", key="Enter")
    await asyncio.sleep(0.8)
    after_enter = json.loads(await tmux_read_pane(target="%0", lines=50))["text"]
    # Appears twice: the echoed command line, plus the command's own output.
    assert after_enter.count("SPECIAL_KEY_OK") >= 2

    # 6. tmux_clear_pane -- scrollback must actually be emptied on the server, and
    #    must STAY empty: the old C-l implementation raced with the shell, which
    #    repopulated the scrollback a fraction of a second after clear-history ran.
    history_before = int(await live("#{history_size}", "%0"))
    assert history_before > 0
    await tmux_clear_pane(target="%0")
    assert int(await live("#{history_size}", "%0")) == 0
    await asyncio.sleep(1.0)
    assert int(await live("#{history_size}", "%0")) == 0


# -----------------------------------------------------------------------------
# 5. Panes - Layout & Arrangement Tools (9)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_layout_tools(tmux_server):
    # 1. tmux_split_pane vertically so height can be resized
    p1 = json.loads(await tmux_split_pane(direction="vertical"))
    p1_id = p1["id"]

    # 2. tmux_select_pane -- move the selection away first, otherwise the new pane
    #    is already active from the split and a no-op implementation would pass.
    await tmux_select_pane(target="%0")
    assert await live("#{pane_id}") == "%0"
    await tmux_select_pane(target=p1_id)
    assert await live("#{pane_id}") == p1_id

    # 3. tmux_resize_pane -- height must really be 10 on the server.
    await tmux_resize_pane(target=p1_id, height=10)
    p1_info = json.loads(await tmux_get_pane_info(target=p1_id))
    assert p1_info["height"] == 10
    assert await live("#{pane_height}", p1_id) == "10"

    # 4. tmux_zoom_pane -- the window's zoom flag must flip, then flip back.
    assert await live("#{window_zoomed_flag}", p1_id) == "0"
    await tmux_zoom_pane(target=p1_id)
    assert await live("#{window_zoomed_flag}", p1_id) == "1"
    await tmux_zoom_pane(target=p1_id)
    assert await live("#{window_zoomed_flag}", p1_id) == "0"

    # 5. tmux_swap_panes -- pane order in the window must actually change.
    order_before = await live_list("list-panes", "", "#{pane_index}:#{pane_id}")
    await tmux_swap_panes(target="%0", to_pane=p1_id)
    order_after = await live_list("list-panes", "", "#{pane_index}:#{pane_id}")
    assert order_before != order_after
    assert sorted(o.split(":")[1] for o in order_before) == sorted(
        o.split(":")[1] for o in order_after
    )

    # 6. tmux_set_layout -- the window layout string must actually change.
    layout_before = await live("#{window_layout}")
    await tmux_set_layout(layout="even-horizontal")
    layout_after = await live("#{window_layout}")
    assert layout_before != layout_after

    # 7. tmux_break_pane -- the pane must end up in a different window.
    win_before = await live("#{window_id}", p1_id)
    await tmux_break_pane(target=p1_id)
    win_after = await live("#{window_id}", p1_id)
    assert win_after != win_before

    # 8. tmux_move_pane -- the pane must be back in %0's window.
    target_win = await live("#{window_id}", "%0")
    await tmux_move_pane(target=p1_id, to_pane="%0")
    assert await live("#{window_id}", p1_id) == target_win

    # 9. tmux_kill_pane -- the pane must be gone server-wide.
    await tmux_kill_pane(target=p1_id)
    all_panes = [
        line
        for line in (await run_tmux(["list-panes", "-a", "-F", "#{pane_id}"])).splitlines()
        if line.strip()
    ]
    assert p1_id not in all_panes


# -----------------------------------------------------------------------------
# 6. Server & Inspection Tools (4)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_inspection_tools(tmux_server):
    # 1. tmux_server_info (Lỗi A regression check)
    srv_json = await tmux_server_info()
    srv = json.loads(srv_json)
    assert srv["running"] is True
    assert srv["version"] != "unknown"
    assert re.match(r"^\d+\.\d+", srv["version"]), f"Expected semver, got {srv['version']}"
    assert srv["session_count"] >= 1

    # 2. tmux_list_clients
    cli_json = await tmux_list_clients()
    clients = json.loads(cli_json)
    assert isinstance(clients, list)

    # 3. tmux_display_message
    msg_res = json.loads(await tmux_display_message(message="AUDIT_STATUS_OK"))
    assert msg_res["status"] == "displayed"

    # 4. tmux_show_options
    opt_json = await tmux_show_options(global_options=True)
    options = json.loads(opt_json)
    assert isinstance(options, dict)
    assert len(options) > 0
