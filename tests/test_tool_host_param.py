"""Tests for per-call host parameter injection and host allowlisting."""

import pytest

from tmux_mcp.config import Config, get_config, set_config
from tmux_mcp.core.context import current_host
from tmux_mcp.core.errors import ProtectedTargetError, UnknownHostError
from tmux_mcp.core.guard import assert_host_allowed
from tmux_mcp.server import _protect, _with_host, create_server

# ---------------------------------------------------------------------------
# 1. Every registered tool carries `host` in its schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_tools_have_host_schema():
    cfg = Config(tool_profile="full")
    app = create_server(cfg)
    tools = await app.list_tools()

    assert len(tools) > 0, "Server registered zero tools"

    for tool in tools:
        schema = tool.input_schema or {}
        props = schema.get("properties", {})
        assert "host" in props, f"Tool '{tool.name}' missing 'host' in input_schema properties"
        host_prop = props["host"]
        assert host_prop.get("type") == "string", f"Tool '{tool.name}' host type is not string"
        assert host_prop.get("default") == "", f"Tool '{tool.name}' host default is not empty string"


# ---------------------------------------------------------------------------
# 2. Schema portability still holds (delegated to existing test)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3. _with_host sets current_host for the call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_with_host_sets_current_host():
    async def stub():
        return current_host()

    wrapped = _with_host(stub)
    set_config(Config())
    try:
        result = await wrapped(host="h1")
        assert result == "h1"
    finally:
        set_config(Config())


@pytest.mark.asyncio
async def test_with_host_no_arg_leaves_config_default():
    async def stub():
        return current_host()

    wrapped = _with_host(stub)
    set_config(Config(remote_host="cfg-host"))
    try:
        result = await wrapped()
        assert result == "cfg-host"
    finally:
        set_config(Config())


# ---------------------------------------------------------------------------
# 4. assert_host_allowed
# ---------------------------------------------------------------------------


def test_assert_host_allowed_empty_host_passes():
    set_config(Config(allowed_hosts=("prod-*",)))
    try:
        assert_host_allowed("")
    finally:
        set_config(Config())


def test_assert_host_allowed_empty_list_allows_any():
    set_config(Config(allowed_hosts=()))
    try:
        assert_host_allowed("anything")
    finally:
        set_config(Config())


def test_assert_host_allowed_raises_for_disallowed_host():
    set_config(Config(allowed_hosts=("prod-1", "staging-*")))
    try:
        with pytest.raises(UnknownHostError) as exc_info:
            assert_host_allowed("prod-9")
        assert "prod-9" in str(exc_info.value)
    finally:
        set_config(Config())


def test_assert_host_allowed_passes_for_matching_pattern():
    set_config(Config(allowed_hosts=("prod-1", "staging-*")))
    try:
        assert_host_allowed("staging-2")
    finally:
        set_config(Config())


# ---------------------------------------------------------------------------
# 5. --protect 'host:prod-*' refuses a mutating call on that host
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_protect_host_pattern_refuses_mutating_call():
    marker = "SHOULD-NEVER-APPEAR"

    cfg = get_config()
    protected_cfg = Config(
        socket_name=cfg.socket_name,
        tool_profile="full",
        protected_targets=("host:prod-*",),
    )
    set_config(protected_cfg)
    try:
        from tmux_mcp.tools.panes import tmux_send_keys

        guarded = _with_host(_protect(tmux_send_keys))
        with pytest.raises(ProtectedTargetError):
            await guarded(target="anything", keys=marker, enter=True, host="prod-1")
    finally:
        set_config(Config())
