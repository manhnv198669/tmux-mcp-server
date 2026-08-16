"""Round 1 hardening: pinned session size, alternate-screen honesty, write protection.

Everything here runs on the isolated TEST_SOCKET from conftest. The nested-tmux
cases start a *second* tmux server on its own socket inside a pane, which is the
same shape as an ssh'd tmux: the outer server sees one pty and no inner panes.
"""

import asyncio
import contextlib
import json

import pytest

from tmux_mcp.config import Config, get_config, set_config
from tmux_mcp.core.errors import ProtectedTargetError
from tmux_mcp.core.guard import assert_target_allowed, parse_patterns, resolve_identities
from tmux_mcp.core.runner import run_tmux
from tmux_mcp.server import create_server
from tmux_mcp.tools.panes import (
    tmux_get_pane_info,
    tmux_read_pane,
    tmux_search_pane,
    tmux_send_keys,
)
from tmux_mcp.tools.sessions import tmux_create_session, tmux_kill_session

INNER_SOCKET = "tmux-mcp-test-inner"


@pytest.fixture(autouse=True)
def _reset_protection():
    """Keep protection patterns from leaking between tests."""
    yield
    cfg = get_config()
    set_config(Config(socket_name=cfg.socket_name, tool_profile=cfg.tool_profile))


async def _nested_pane(session: str) -> str:
    """Create a session whose pane runs another tmux server, and return its pane id."""
    await tmux_create_session(name=session, width=80, height=24)
    pane_id = json.loads(await tmux_get_pane_info(f"{session}:0.0"))["id"]

    await tmux_send_keys(
        target=pane_id,
        keys=f"tmux -L {INNER_SOCKET} new-session -A -s inner",
        enter=True,
    )
    # Wait for the inner server to claim the alternate screen.
    for _ in range(40):
        await asyncio.sleep(0.25)
        if json.loads(await tmux_get_pane_info(pane_id))["alternate_on"]:
            break
    return pane_id


async def _kill_inner() -> None:
    with contextlib.suppress(Exception):
        await run_tmux(["kill-server"], override_socket_name=INNER_SOCKET)


# --------------------------------------------------------------------------
# create_session honours the size it was given
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_pins_requested_size(tmux_server):
    """Without window-size manual tmux silently resizes to the newest client."""
    result = json.loads(await tmux_create_session(name="sized", width=100, height=30))

    assert result["width"] == 100
    assert result["height"] == 30

    live = await run_tmux(
        ["display-message", "-p", "-t", "sized", "#{window_width}x#{window_height}"]
    )
    assert live.strip() == "100x30"

    await tmux_kill_session("sized")


@pytest.mark.asyncio
async def test_create_session_without_size_is_unpinned(tmux_server):
    """Omitting width/height must not start pinning windows as a side effect."""
    await tmux_create_session(name="unsized")
    mode = await run_tmux(["show-options", "-w", "-t", "unsized", "window-size"])
    assert "manual" not in mode
    await tmux_kill_session("unsized")


# --------------------------------------------------------------------------
# alternate screen: report the loss instead of hiding it
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_pane_reports_scrollback_available(tmux_server):
    await tmux_create_session(name="plain", width=80, height=24)
    data = json.loads(await tmux_read_pane(target="plain:0.0", lines=50))

    assert data["scrollback_available"] is True
    assert data["alternate_on"] is False
    assert "warning" not in data

    await tmux_kill_session("plain")


@pytest.mark.asyncio
async def test_nested_tmux_pane_is_flagged_and_readable(tmux_server):
    pane_id = await _nested_pane("nest")
    try:
        info = json.loads(await tmux_get_pane_info(pane_id))
        assert info["alternate_on"] is True
        # The mislabelled field used to carry pane_in_mode instead.
        assert info["zoomed"] is False
        assert "in_mode" in info

        data = json.loads(await tmux_read_pane(target=pane_id, full_history=True))
        # Reading still works: the inner screen is just text in the outer pane.
        assert data["text"].strip() != ""
        assert data["scrollback_available"] is False
        assert data["alternate_on"] is True
        # The honesty fix: history was asked for and could not be delivered.
        assert data["truncated"] is True
        assert "alternate screen" in data["warning"]
    finally:
        await _kill_inner()
        await tmux_kill_session("nest")


@pytest.mark.asyncio
async def test_search_pane_admits_it_only_saw_the_visible_screen(tmux_server):
    pane_id = await _nested_pane("nest_search")
    try:
        res = json.loads(await tmux_search_pane(target=pane_id, pattern="definitely-absent"))
        assert res["total_matches"] == 0
        assert res["scrollback_available"] is False
        assert "does NOT mean" in res["warning"]
        assert res["searched_lines"] > 0
    finally:
        await _kill_inner()
        await tmux_kill_session("nest_search")


@pytest.mark.asyncio
async def test_join_wrapped_rejoins_a_split_value(tmux_server):
    """A value longer than the pane width must come back as one line with -J."""
    await tmux_create_session(name="wrap", width=40, height=10)
    token = "X" * 90
    await tmux_send_keys(target="wrap:0.0", keys=f"printf '{token}\\n'", enter=True)
    await asyncio.sleep(0.6)

    split = json.loads(await tmux_read_pane(target="wrap:0.0", lines=20))
    joined = json.loads(await tmux_read_pane(target="wrap:0.0", lines=20, join_wrapped=True))

    assert token not in split["text"]  # wrapped across rows at width 40
    assert token in joined["text"]

    await tmux_kill_session("wrap")


# --------------------------------------------------------------------------
# per-target write protection
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identities_cover_every_way_to_name_a_pane(tmux_server):
    await tmux_create_session(name="ident", width=80, height=24)
    identities = await resolve_identities("ident:0.0")

    assert "ident" in identities
    assert "ident:0" in identities
    assert "ident:0.0" in identities
    assert any(i.startswith("%") for i in identities)
    assert any(i.startswith("$") for i in identities)

    await tmux_kill_session("ident")


@pytest.mark.asyncio
async def test_protection_matches_across_naming_forms(tmux_server):
    """A rule written as session:window must also stop a raw %pane id."""
    await tmux_create_session(name="prod", width=80, height=24)
    pane_id = json.loads(await tmux_get_pane_info("prod:0.0"))["id"]

    cfg = get_config()
    set_config(
        Config(
            socket_name=cfg.socket_name,
            tool_profile=cfg.tool_profile,
            protected_targets=("prod:0*",),
        )
    )

    for form in ("prod:0.0", "prod:0", pane_id):
        with pytest.raises(ProtectedTargetError):
            await assert_target_allowed(form)

    await tmux_kill_session("prod")


@pytest.mark.asyncio
async def test_protection_leaves_other_sessions_writable(tmux_server):
    await tmux_create_session(name="prod2", width=80, height=24)
    await tmux_create_session(name="scratch", width=80, height=24)

    cfg = get_config()
    set_config(
        Config(
            socket_name=cfg.socket_name,
            tool_profile=cfg.tool_profile,
            protected_targets=("prod2",),
        )
    )

    await assert_target_allowed("scratch:0.0")  # must not raise
    with pytest.raises(ProtectedTargetError):
        await assert_target_allowed("prod2:0.0")

    await tmux_kill_session("prod2")
    await tmux_kill_session("scratch")


@pytest.mark.asyncio
async def test_registered_tool_refuses_protected_target(tmux_server):
    """The block happens at the server layer, before tmux is touched."""
    await tmux_create_session(name="prod3", width=80, height=24)
    marker = "SHOULD-NEVER-APPEAR"

    cfg = get_config()
    protected_cfg = Config(
        socket_name=cfg.socket_name,
        tool_profile="full",
        protected_targets=("prod3*",),
    )
    create_server(protected_cfg)

    from tmux_mcp.server import _protect

    guarded_send = _protect(tmux_send_keys)
    with pytest.raises(ProtectedTargetError):
        await guarded_send(target="prod3:0.0", keys=marker, enter=True)

    # Nothing reached the pane.
    data = json.loads(await tmux_read_pane(target="prod3:0.0", lines=50))
    assert marker not in data["text"]

    await tmux_kill_session("prod3")


@pytest.mark.asyncio
async def test_protection_checks_the_implicit_current_pane(tmux_server):
    """An omitted target means tmux's current pane, so it must be resolved too."""
    identities = await resolve_identities("")
    assert identities and identities[0]

    cfg = get_config()
    set_config(
        Config(
            socket_name=cfg.socket_name,
            tool_profile=cfg.tool_profile,
            protected_targets=(identities[0],),
        )
    )

    with pytest.raises(ProtectedTargetError):
        await assert_target_allowed("")


@pytest.mark.asyncio
async def test_no_patterns_means_no_wrapping(tmux_server):
    """Zero configured patterns must leave mutating tools completely untouched."""
    await tmux_create_session(name="free", width=80, height=24)
    await assert_target_allowed("free:0.0")  # no config, no raise
    await tmux_kill_session("free")


def test_parse_patterns_flattens_flags_and_commas():
    assert parse_patterns(["a", "b,c", " d , "]) == ("a", "b", "c", "d")
    assert parse_patterns([""]) == ()
    assert parse_patterns(None) == ()
