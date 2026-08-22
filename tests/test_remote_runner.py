"""Tests for driving a tmux server on another host over ssh.

Nothing here talks to a real host: the point is the argv handed to ssh. A tmux
format string is full of characters a remote shell would happily reinterpret
(`#{...}`, `;`, \x1f), so the quoting is the part that has to be right.
"""

import asyncio
import shlex

import pytest

from tmux_mcp.config import Config, set_config
from tmux_mcp.core.errors import RemoteConnectionError, TmuxNotRunningError
from tmux_mcp.core.runner import build_argv, run_tmux
from tmux_mcp.exec.shells import build_epilogue

PANE_FORMAT = "#{pane_id}\x1f#{pane_current_command}"


@pytest.fixture
def remote_config():
    """Point the global config at a remote host, restoring the local one after."""

    def _apply(**kwargs) -> Config:
        cfg = Config(remote_host="prod-01", **kwargs)
        set_config(cfg)
        return cfg

    yield _apply
    set_config(Config())


class FakeProc:
    """Stand-in for the asyncio subprocess, with a preset exit code and stderr."""

    def __init__(self, returncode: int, stderr: bytes = b""):
        self.returncode = returncode
        self._stderr = stderr
        self.pid = 4242

    async def communicate(self):
        return (b"", self._stderr)

    def kill(self):
        pass

    async def wait(self):
        return self.returncode


@pytest.fixture
def fake_exec(monkeypatch):
    """Replace process creation with a fake, and record the argv it was given."""
    recorded: list[list[str]] = []

    def _install(proc: FakeProc):
        async def _fake(*argv, **kwargs):
            recorded.append(list(argv))
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake)
        return recorded

    return _install


def test_local_argv_is_plain_tmux():
    set_config(Config())
    argv = build_argv(["list-panes"], [])
    assert argv[0] == "tmux"
    assert "ssh" not in argv


def test_remote_argv_wraps_tmux_in_ssh(remote_config):
    remote_config()
    argv = build_argv(["list-panes"], [])
    assert argv[0] == "ssh"
    assert "BatchMode=yes" in argv
    assert "prod-01" in argv
    assert argv[-1].startswith("tmux ")


def test_remote_argv_survives_a_quoting_round_trip(remote_config):
    """The remote shell must hand tmux back exactly the argv we started with."""
    remote_config()
    tmux_args = ["list-panes", "-F", PANE_FORMAT]
    argv = build_argv(tmux_args, [])
    assert shlex.split(argv[-1]) == ["tmux", *tmux_args]


def test_remote_argv_keeps_socket_flags_and_batch_separators(remote_config):
    """`;` is tmux's own separator and must not reach the remote shell unquoted."""
    remote_config()
    argv = build_argv(["list-panes", ";", "list-windows"], ["-L", "sock name"])
    assert shlex.split(argv[-1]) == [
        "tmux",
        "-L",
        "sock name",
        "list-panes",
        ";",
        "list-windows",
    ]


def test_ssh_opts_precede_the_host(remote_config):
    remote_config(remote_ssh_opts=("-p", "2222"))
    argv = build_argv(["list-panes"], [])
    assert "-p" in argv and "2222" in argv
    assert argv.index("2222") < argv.index("prod-01")


@pytest.mark.asyncio
async def test_ssh_failure_is_not_reported_as_a_tmux_failure(remote_config, fake_exec):
    """Exit 255 is ssh giving up, which says nothing about the remote tmux."""
    remote_config()
    fake_exec(FakeProc(255, b"ssh: connect to host prod-01 port 22: Connection refused"))

    with pytest.raises(RemoteConnectionError) as excinfo:
        await run_tmux(["list-panes"])

    assert "prod-01" in str(excinfo.value)
    assert "Connection refused" in str(excinfo.value)


@pytest.mark.asyncio
async def test_remote_server_down_still_raises_not_running(remote_config, fake_exec):
    """The remote tmux's own stderr comes back through ssh unchanged."""
    remote_config()
    fake_exec(FakeProc(1, b"no server running on /tmp/tmux-1000/default"))

    with pytest.raises(TmuxNotRunningError):
        await run_tmux(["list-panes"])


def test_epilogue_uses_a_bare_tmux_binary_when_remote():
    """A locally resolved path like /opt/homebrew/bin/tmux does not exist over there."""
    set_config(Config())
    remote = build_epilogue("echo hi", "/tmp/rc", "chan", cmd_id="abc", remote=True)
    assert "'tmux'" in remote
    assert "/bin/tmux" not in remote


def test_epilogue_keeps_the_resolved_path_when_local():
    set_config(Config())
    local = build_epilogue("echo hi", "/tmp/rc", "chan", cmd_id="abc", remote=False)
    assert "tmux" in local
