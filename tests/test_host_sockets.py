"""Tests for per-host socket overrides."""

import pytest

from tmux_mcp.config import Config, set_config
from tmux_mcp.core.context import use_host
from tmux_mcp.core.runner import get_socket_args
from tmux_mcp.exec.shells import build_epilogue


class TestGetSocketArgs:
    @pytest.fixture(autouse=True)
    def reset_config(self):
        set_config(Config())
        yield
        set_config(Config())

    def test_no_host_active_ignores_host_sockets(self):
        set_config(Config(host_sockets={"h1": "/tmp/x"}))
        assert get_socket_args() == []

    def test_host_active_matches_exact_path(self):
        set_config(Config(host_sockets={"h1": "/tmp/x"}))
        with use_host("h1"):
            assert get_socket_args() == ["-S", "/tmp/x"]

    def test_host_active_matches_bare_name(self):
        set_config(Config(host_sockets={"h1": "work"}))
        with use_host("h1"):
            assert get_socket_args() == ["-L", "work"]

    def test_host_active_matches_fnmatch_pattern(self):
        set_config(Config(host_sockets={"prod-*": "/tmp/p"}))
        with use_host("prod-7"):
            assert get_socket_args() == ["-S", "/tmp/p"]

    def test_explicit_override_beats_host_override(self):
        set_config(Config(host_sockets={"h1": "/tmp/override"}))
        with use_host("h1"):
            assert get_socket_args(override_socket_path="/tmp/explicit") == [
                "-S",
                "/tmp/explicit",
            ]

    def test_host_with_no_entry_falls_back_to_process_level(self):
        set_config(Config(socket_name="local-sock", host_sockets={"h1": "/tmp/x"}))
        with use_host("other"):
            assert get_socket_args() == ["-L", "local-sock"]

    def test_build_epilogue_resolves_per_host(self):
        set_config(Config(host_sockets={"h1": "/tmp/x"}))
        with use_host("h1"):
            epilogue = build_epilogue("echo hi", "/tmp/rc", "chan", cmd_id="abc")
        assert "-S /tmp/x" in epilogue


class TestCliHostSocket:
    def test_parse_simple_value(self, monkeypatch):
        from tmux_mcp.__main__ import parse_args

        monkeypatch.setattr("sys.argv", ["tmux-mcp-server", "--host-socket", "a=/tmp/s"])
        cfg = parse_args()
        assert cfg.host_sockets == {"a": "/tmp/s"}

    def test_parse_value_with_equals_in_socket_path(self, monkeypatch):
        from tmux_mcp.__main__ import parse_args

        monkeypatch.setattr(
            "sys.argv", ["tmux-mcp-server", "--host-socket", "a=/tmp/s=1"]
        )
        cfg = parse_args()
        assert cfg.host_sockets == {"a": "/tmp/s=1"}

    def test_parse_no_equals_raises_error(self, monkeypatch):
        from tmux_mcp.__main__ import parse_args

        monkeypatch.setattr("sys.argv", ["tmux-mcp-server", "--host-socket", "bad"])
        with pytest.raises(SystemExit):
            parse_args()

    def test_parse_env_var_comma_separated(self, monkeypatch):
        from tmux_mcp.__main__ import parse_args

        monkeypatch.setenv("TMUX_MCP_HOST_SOCKETS", "a=/tmp/s,b=work")
        monkeypatch.setattr("sys.argv", ["tmux-mcp-server"])
        cfg = parse_args()
        assert cfg.host_sockets == {"a": "/tmp/s", "b": "work"}
