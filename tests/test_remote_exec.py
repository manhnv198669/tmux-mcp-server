"""Tests for remote exec facade and assume_partial behavior."""

import time

import pytest

from tmux_mcp.config import Config, set_config
from tmux_mcp.core import fsops
from tmux_mcp.core.models import CommandRunModel
from tmux_mcp.exec.engine import MAX_OUTPUT_BYTES, extract_clean_output, finalize_record
from tmux_mcp.exec.registry import CommandRecord


def test_extract_clean_output_assume_partial_true():
    text = "hello\nworld\n"
    out, truncated = extract_clean_output(text, "cmd_x", assume_partial=True)
    assert out != ""
    assert truncated is True
    assert "hello" in out


def test_extract_clean_output_assume_partial_false():
    text = "hello\nworld\n"
    out, truncated = extract_clean_output(text, "cmd_x", assume_partial=False)
    assert out == ""
    assert truncated is False


def test_extract_clean_output_assume_partial_removes_markers():
    cmd_id = "cmd_x"
    # markers for a different command should be stripped when assume_partial=True
    text = "__TMUX_MCP_START_other__\nhello\n__TMUX_MCP_END_other__\nworld\n"
    out, truncated = extract_clean_output(text, cmd_id, assume_partial=True)
    assert truncated is True
    assert "__TMUX_MCP_START_" not in out
    assert "__TMUX_MCP_END_" not in out
    assert "hello" in out or "world" in out


@pytest.mark.asyncio
async def test_remote_finalize_record_via_fsops(monkeypatch):
    set_config(Config(remote_host="prod-01", remote_tmp_dir="/tmp"))
    cmd_id = "cmd_remote123"
    cap_file = "/tmp/tmux-mcp-cmd_remote123/cap.log"
    rc_file = "/tmp/tmux-mcp-cmd_remote123/rc.txt"
    recorded: list[str] = []

    async def fake_run_remote_shell(cmdline: str, **_kwargs):
        recorded.append(cmdline)
        if "rc.txt" in cmdline:
            return "0"
        if "cap.log" in cmdline:
            return f"__TMUX_MCP_START_{cmd_id}__\nhello from remote\n__TMUX_MCP_END_{cmd_id}__\n"
        return ""

    monkeypatch.setattr(fsops, "run_remote_shell", fake_run_remote_shell)

    async def fake_run_tmux(*_args, **_kwargs):
        return ""

    monkeypatch.setattr("tmux_mcp.exec.engine.run_tmux", fake_run_tmux)
    # also patch registry run_tmux not needed here but finalize uses engine run_tmux
    # patch history to no-op to avoid file writes
    monkeypatch.setattr("tmux_mcp.exec.engine.record_finished", lambda *a, **k: None)

    try:
        model = CommandRunModel(
            command_id=cmd_id,
            pane_id="%0",
            command="echo hi",
            status="running",
            exit_code=-1,
            output="",
            truncated=False,
            created_at=time.time(),
        )
        rec = CommandRecord(
            model=model,
            tmp_dir="/tmp/tmux-mcp-cmd_remote123",
            channel="tmux-mcp-wait-cmd_remote123",
            cap_file=cap_file,
            rc_file=rc_file,
            last_accessed=time.time(),
            cwd="",
            pane="%0",
        )
        result = await finalize_record(rec)
        assert result.exit_code == 0
        assert result.status == "completed"
        assert result.output == "hello from remote"
        # Verify fsops drove remote reads
        assert any("rc.txt" in c for c in recorded)
        assert any("cap.log" in c for c in recorded)
    finally:
        set_config(Config())


@pytest.mark.asyncio
async def test_local_finalize_record_reads_real_files(monkeypatch, tmp_path):
    set_config(Config())
    cmd_id = "cmd_local123"
    tmp_dir = tmp_path / f"tmux-mcp-{cmd_id}"
    tmp_dir.mkdir(parents=True)
    cap_file = tmp_dir / "cap.log"
    rc_file = tmp_dir / "rc.txt"
    rc_file.write_text("42")
    cap_file.write_text(
        f"__TMUX_MCP_START_{cmd_id}__\nhello local\n__TMUX_MCP_END_{cmd_id}__\n"
    )

    async def fake_run_tmux(*_args, **_kwargs):
        return ""

    monkeypatch.setattr("tmux_mcp.exec.engine.run_tmux", fake_run_tmux)
    monkeypatch.setattr("tmux_mcp.exec.engine.record_finished", lambda *a, **k: None)

    # ensure fsops does not call remote
    async def _fail(*_a, **_k):
        raise AssertionError("run_remote_shell should not be called in local mode")

    monkeypatch.setattr(fsops, "run_remote_shell", _fail)

    try:
        model = CommandRunModel(
            command_id=cmd_id,
            pane_id="%0",
            command="echo hi",
            status="running",
            exit_code=-1,
            output="",
            truncated=False,
            created_at=time.time(),
        )
        rec = CommandRecord(
            model=model,
            tmp_dir=str(tmp_dir),
            channel=f"tmux-mcp-wait-{cmd_id}",
            cap_file=str(cap_file),
            rc_file=str(rc_file),
            last_accessed=time.time(),
            cwd="",
            pane="%0",
        )
        result = await finalize_record(rec)
        assert result.exit_code == 42
        assert result.status == "failed"
        assert result.output == "hello local"
        assert result.truncated is False
    finally:
        set_config(Config())


@pytest.mark.asyncio
async def test_remote_make_dir_uses_fsops(monkeypatch):
    set_config(Config(remote_host="prod-01", remote_tmp_dir="/tmp"))
    recorded: list[str] = []

    async def fake(cmdline: str, **_kwargs):
        recorded.append(cmdline)
        return ""

    monkeypatch.setattr(fsops, "run_remote_shell", fake)
    try:
        await fsops.make_dir("/tmp/tmux-mcp-cmd_test")
        assert len(recorded) == 1
        assert "mkdir -p" in recorded[0]
        recorded.clear()
        await fsops.read_text("/tmp/tmux-mcp-cmd_test/cap.log", max_bytes=MAX_OUTPUT_BYTES * 2)
        assert len(recorded) == 1
        assert "tail -c" in recorded[0] or "cat" in recorded[0]
    finally:
        set_config(Config())
