"""Tests for Phase 3 Execution Engine (pipe-pane + wait-for)."""

import asyncio
import json
import pytest

from tmux_mcp.core.runner import run_tmux
from tmux_mcp.tools.execution import (
    tmux_cancel_command,
    tmux_get_command_result,
    tmux_run_command,
    tmux_wait_command,
)
from tmux_mcp.tools.layout import tmux_split_pane
from tmux_mcp.tools.panes import tmux_send_keys, tmux_send_special_key


@pytest.mark.asyncio
async def test_exec_exit_code(tmux_server):
    # Test subshell exit code 42 (Test #4)
    res_json = await tmux_run_command(command="(exit 42)", timeout=10.0)
    res = json.loads(res_json)
    assert res["status"] == "failed"
    assert res["exit_code"] == 42


@pytest.mark.asyncio
async def test_exec_long_output(tmux_server):
    # Test seq 1 50000 (Test #3 - Output length and clean extraction verification)
    res_json = await tmux_run_command(command="seq 1 50000", timeout=30.0)
    res = json.loads(res_json)
    assert res["status"] == "completed"
    assert res["exit_code"] == 0

    lines = [line.strip() for line in res["output"].splitlines() if line.strip().isdigit()]
    assert len(lines) == 50000, f"Expected 50000 lines, got {len(lines)}"
    assert lines[0] == "1"
    assert lines[-1] == "50000"

    assert "wait-for" not in res["output"]
    assert "rc.txt" not in res["output"]


@pytest.mark.asyncio
async def test_exec_partial_output_on_timeout(tmux_server):
    # Lỗi 2: Partial output when command is still running or timed out
    res_json = await tmux_run_command(command="echo PARTIAL_LINE; sleep 20", timeout=2.0)
    res = json.loads(res_json)

    assert res["status"] == "running"
    assert "PARTIAL_LINE" in res["output"]
    assert "wait-for" not in res["output"]
    assert "rc.txt" not in res["output"]

    # Cancel command
    await tmux_cancel_command(command_id=res["command_id"])


@pytest.mark.asyncio
async def test_multiline_command_rejection(tmux_server):
    # Test #8: Multiline commands should be rejected with error
    res_json = await tmux_run_command(command="echo line1\necho line2")
    res = json.loads(res_json)
    assert "error" in res
    assert "Multiline" in res["error"]


@pytest.mark.asyncio
async def test_pipe_pane_cleanup_after_cancel(tmux_server):
    # Lỗi 3: Verify pipe-pane stream is turned off after cancel_command
    res_json = await tmux_run_command(command="sleep 30", timeout=2.0)
    res = json.loads(res_json)
    assert res["status"] == "running"

    p_before = (await run_tmux(["list-panes", "-t", "%0", "-F", "#{pane_pipe}"])).strip()
    assert p_before == "1", "Expected pipe-pane active while running"

    await tmux_cancel_command(command_id=res["command_id"])
    await asyncio.sleep(0.5)

    p_after = (await run_tmux(["list-panes", "-t", "%0", "-F", "#{pane_pipe}"])).strip()
    assert p_after == "0", "Expected pipe-pane turned off after cancel_command"


@pytest.mark.asyncio
async def test_pane_busy_guard_python_repl(tmux_server):
    # Lỗi 1: Test #1 - Python REPL in pane must be rejected by busy guard
    split_json = await tmux_split_pane(direction="vertical")
    pane = json.loads(split_json)
    pane_id = pane["id"]

    await asyncio.sleep(1.0)
    await tmux_send_keys(target=pane_id, keys="python3", enter=True)
    await asyncio.sleep(1.5)

    res_json = await tmux_run_command(target=pane_id, command="echo 123")
    res = json.loads(res_json)

    assert "error" in res, f"Expected busy error for python3 REPL, got {res}"
    assert "busy" in res["error"]

    await tmux_send_keys(target=pane_id, keys="exit()", enter=True)


@pytest.mark.asyncio
async def test_pane_busy_guard_cat(tmux_server):
    # Lỗi 1: Test #2 - cat in pane must be rejected by busy guard
    split_json = await tmux_split_pane(direction="vertical")
    pane = json.loads(split_json)
    pane_id = pane["id"]

    await asyncio.sleep(1.0)
    await tmux_send_keys(target=pane_id, keys="cat", enter=True)
    await asyncio.sleep(1.0)

    res_json = await tmux_run_command(target=pane_id, command="echo 123")
    res = json.loads(res_json)

    assert "error" in res, f"Expected busy error for cat, got {res}"
    assert "busy" in res["error"]

    await tmux_send_special_key(target=pane_id, key="C-c")


@pytest.mark.asyncio
async def test_pane_busy_guard_less(tmux_server):
    # Lỗi 1: Test #3 - less /etc/hosts in pane must be rejected by busy guard
    split_json = await tmux_split_pane(direction="vertical")
    pane = json.loads(split_json)
    pane_id = pane["id"]

    await asyncio.sleep(1.0)
    await tmux_send_keys(target=pane_id, keys="less /etc/hosts", enter=True)
    await asyncio.sleep(1.0)

    res_json = await tmux_run_command(target=pane_id, command="echo 123")
    res = json.loads(res_json)

    assert "error" in res, f"Expected busy error for less, got {res}"
    assert "busy" in res["error"]

    await tmux_send_keys(target=pane_id, keys="q", enter=False)
