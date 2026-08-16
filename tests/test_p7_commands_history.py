"""The server's own command log, kept out of the user's shell history.

Two things matter here beyond "a line got written": the log must never be able to
break or slow the command it is recording, and a field must never be able to forge
a column in a file people will grep.
"""

import asyncio
import json
import os
import sys

import pytest

from tmux_mcp.config import Config, get_config, set_config
from tmux_mcp.core.models import CommandRunModel
from tmux_mcp.exec.history import SEP, record_finished, record_started
from tmux_mcp.tools.execution import tmux_run_command
from tmux_mcp.tools.sessions import tmux_create_session, tmux_kill_session


def _model(command: str = "echo hi", status: str = "running", exit_code: int = -1):
    return CommandRunModel(
        command_id="cmd_test123",
        pane_id="%7",
        command=command,
        status=status,
        exit_code=exit_code,
        created_at=1000.0,
    )


def _lines(path: str) -> list[list[str]]:
    with open(path) as f:
        return [line.rstrip("\n").split(SEP) for line in f if line.strip()]


def _history_path() -> str:
    return get_config().commands_history_file


async def _session(name: str) -> str:
    """Create a session and let its shell come up.

    Without the settle, run_command can catch pane_current_command before the shell
    has claimed the pane and reject it as a non-shell process.
    """
    await tmux_create_session(name=name, width=80, height=20)
    await asyncio.sleep(0.5)
    return f"{name}:0.0"


def _run_ok(raw: str) -> dict:
    res = json.loads(raw)
    assert "error" not in res, res
    return res


def test_records_dispatch_and_result():
    record_started(_model(), cwd="/tmp/work")
    record_finished(_model(status="completed", exit_code=0), cwd="/tmp/work")

    rows = _lines(_history_path())
    assert len(rows) == 2

    ts, event, cmd_id, pane, exit_col, elapsed, cwd, command = rows[0]
    assert event == "RUN"
    assert cmd_id == "cmd_test123"
    assert pane == "%7"
    assert (exit_col, elapsed) == ("-", "-")
    assert cwd == "/tmp/work"
    assert command == "echo hi"
    assert ts.startswith("20")

    assert rows[1][1] == "OK"
    assert rows[1][4] == "0"
    assert rows[1][5].endswith("s")


def test_event_column_distinguishes_outcomes():
    record_finished(_model(status="failed", exit_code=2))
    record_finished(_model(status="cancelled"))

    rows = _lines(_history_path())
    assert [r[1] for r in rows] == ["FAIL", "CANCEL"]
    assert rows[0][4] == "2"
    # A cancelled command has no exit code to report; "-1" would read as one.
    assert rows[1][4] == "-"


def test_appends_and_creates_missing_parent(tmp_path):
    path = tmp_path / "nested" / "dir" / "history.log"
    set_config(Config(commands_history_file=str(path)))

    record_started(_model(command="first"))
    record_started(_model(command="second"))

    rows = _lines(str(path))
    assert [r[7] for r in rows] == ["first", "second"]


def test_disabled_writes_nothing(tmp_path):
    path = tmp_path / "history.log"
    set_config(Config(commands_history_file=str(path), save_commands_history=False))

    record_started(_model())
    record_finished(_model(status="completed", exit_code=0))

    assert not path.exists()


def test_field_cannot_forge_a_column():
    """A tab inside a command would otherwise shift every column after it."""
    record_started(_model(command="echo a\tb\nrm -rf /"), cwd="/tmp/we\tird")

    rows = _lines(_history_path())
    assert len(rows) == 1, "embedded newline split the record into two lines"
    assert len(rows[0]) == 8
    assert rows[0][7] == "echo a b rm -rf /"


def test_write_failure_does_not_raise(tmp_path):
    """A broken path must not take the command down with it."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    set_config(Config(commands_history_file=str(blocker / "history.log")))

    record_started(_model())  # must not raise


@pytest.mark.skipif(sys.platform == "win32", reason="symlink semantics differ")
def test_symlink_at_the_log_path_is_refused(tmp_path):
    """The default lives in a world-writable /tmp, so the log must not follow a link."""
    victim = tmp_path / "victim.txt"
    victim.write_text("original\n")
    link = tmp_path / "history.log"
    os.symlink(victim, link)

    set_config(Config(commands_history_file=str(link)))
    record_started(_model())

    assert victim.read_text() == "original\n"


async def test_run_command_writes_both_events(tmux_server):
    target = await _session("hist_ok")
    try:
        res = _run_ok(await tmux_run_command(target=target, command="echo LOGGED"))
        assert res["status"] == "completed"

        rows = _lines(_history_path())
        assert [r[1] for r in rows] == ["RUN", "OK"]

        run_row, end_row = rows
        assert run_row[2] == end_row[2] == res["command_id"]
        assert run_row[7] == "echo LOGGED"
        assert end_row[4] == "0"
        # The resolved pane id, not the "hist_ok:0.0" string the caller passed:
        # session names get reused, %ids do not.
        assert run_row[3].startswith("%")
        assert end_row[3] == run_row[3]
        # cwd is captured at dispatch, so it is present on both records.
        assert run_row[6].startswith("/")
        assert end_row[6] == run_row[6]
    finally:
        await tmux_kill_session("hist_ok")


async def test_failing_command_is_recorded_with_its_exit_code(tmux_server):
    target = await _session("hist_fail")
    try:
        # A subshell, so the exit code is non-zero without taking the pane's shell
        # (and therefore the session) down with it.
        res = _run_ok(await tmux_run_command(target=target, command="(exit 3)"))
        assert res["exit_code"] == 3

        rows = _lines(_history_path())
        assert rows[-1][1] == "FAIL"
        assert rows[-1][4] == "3"
    finally:
        await tmux_kill_session("hist_fail")


async def test_result_is_logged_once_however_often_it_is_polled(tmux_server):
    """Polling a finished command must not append a duplicate record."""
    from tmux_mcp.tools.execution import tmux_get_command_result

    target = await _session("hist_once")
    try:
        res = _run_ok(await tmux_run_command(target=target, command="echo ONCE"))
        for _ in range(3):
            await tmux_get_command_result(res["command_id"])

        rows = _lines(_history_path())
        assert [r[1] for r in rows] == ["RUN", "OK"]
    finally:
        await tmux_kill_session("hist_once")


def test_cli_flags_reach_the_config(monkeypatch):
    from tmux_mcp.__main__ import parse_args
    from tmux_mcp.config import DEFAULT_COMMANDS_HISTORY_FILE

    monkeypatch.setattr(sys, "argv", ["tmux-mcp-server"])
    assert parse_args().commands_history_file == DEFAULT_COMMANDS_HISTORY_FILE
    assert parse_args().save_commands_history is True

    monkeypatch.setattr(
        sys, "argv", ["tmux-mcp-server", "--commands-history-file", "/tmp/custom.log"]
    )
    cfg = parse_args()
    assert cfg.commands_history_file == "/tmp/custom.log"
    assert cfg.save_commands_history is True

    # Disabling wins over a path: asking for no record at all is the stronger intent.
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tmux-mcp-server",
            "--commands-history-file",
            "/tmp/custom.log",
            "--no-save-commands-history",
        ],
    )
    assert parse_args().save_commands_history is False
