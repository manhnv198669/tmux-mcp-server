"""Writing into a pane that someone is viewing in copy-mode.

The failure this guards against is not a clean rejection. With the pane in copy-mode,
tmux feeds each key to the mode's key table; leading characters are consumed as
copy-mode commands, one of them cancels the mode, and the tail falls through to the
shell and executes. Sending "echo MARKER" that way lands "RKER" in the shell.
"""

import asyncio
import json

import pytest

from tmux_mcp.core.errors import PaneInModeError
from tmux_mcp.core.guard import assert_pane_writable
from tmux_mcp.core.runner import run_tmux
from tmux_mcp.tools.execution import tmux_run_command
from tmux_mcp.tools.panes import (
    tmux_get_pane_info,
    tmux_read_pane,
    tmux_send_keys,
    tmux_send_special_key,
)
from tmux_mcp.tools.sessions import tmux_create_session, tmux_kill_session


async def _pane(name: str) -> str:
    await tmux_create_session(name=name, width=80, height=20)
    await asyncio.sleep(0.4)
    return json.loads(await tmux_get_pane_info(f"{name}:0.0"))["id"]


async def _enter_copy_mode(pane_id: str) -> None:
    await run_tmux(["copy-mode", "-t", pane_id])
    await asyncio.sleep(0.3)
    assert json.loads(await tmux_get_pane_info(pane_id))["in_mode"] is True


@pytest.mark.asyncio
async def test_send_keys_refuses_pane_in_copy_mode(tmux_server):
    pane_id = await _pane("cm_keys")
    try:
        await _enter_copy_mode(pane_id)

        with pytest.raises(PaneInModeError):
            await tmux_send_keys(target=pane_id, keys="echo MARKER", enter=True)

        # The refusal must be total: no fragment reached the shell, and the human's
        # view was left where they put it.
        await asyncio.sleep(0.5)
        assert json.loads(await tmux_get_pane_info(pane_id))["in_mode"] is True
        text = json.loads(await tmux_read_pane(target=pane_id, lines=40))["text"]
        assert "MARKER" not in text
        assert "command not found" not in text
    finally:
        await tmux_kill_session("cm_keys")


@pytest.mark.asyncio
async def test_send_special_key_refuses_pane_in_copy_mode(tmux_server):
    pane_id = await _pane("cm_special")
    try:
        await _enter_copy_mode(pane_id)
        with pytest.raises(PaneInModeError):
            await tmux_send_special_key(target=pane_id, key="Enter")
        assert json.loads(await tmux_get_pane_info(pane_id))["in_mode"] is True
    finally:
        await tmux_kill_session("cm_special")


@pytest.mark.asyncio
async def test_run_command_returns_error_instead_of_raising(tmux_server):
    """run_command reports failures as JSON, so it must stay consistent here."""
    pane_id = await _pane("cm_run")
    try:
        await _enter_copy_mode(pane_id)
        res = json.loads(await tmux_run_command(target=pane_id, command="echo MARKER"))

        assert "error" in res
        assert res["pane_mode"] == "copy-mode"
        assert "exit_copy_mode" in res["error"]

        text = json.loads(await tmux_read_pane(target=pane_id, lines=40))["text"]
        assert "MARKER" not in text
    finally:
        await tmux_kill_session("cm_run")


@pytest.mark.asyncio
async def test_exit_copy_mode_opt_in_lets_the_write_through(tmux_server):
    pane_id = await _pane("cm_optin")
    try:
        await _enter_copy_mode(pane_id)

        await tmux_send_keys(
            target=pane_id, keys="echo MARKER_OK", enter=True, exit_copy_mode=True
        )
        await asyncio.sleep(1.0)

        info = json.loads(await tmux_get_pane_info(pane_id))
        assert info["in_mode"] is False

        text = json.loads(await tmux_read_pane(target=pane_id, lines=40))["text"]
        assert "MARKER_OK" in text
        # Whole command, not a fragment of it.
        assert "command not found" not in text
    finally:
        await tmux_kill_session("cm_optin")


@pytest.mark.asyncio
async def test_normal_pane_is_unaffected(tmux_server):
    """The guard must be invisible when nobody is viewing the pane."""
    pane_id = await _pane("cm_normal")
    try:
        await assert_pane_writable(pane_id)  # must not raise
        await tmux_send_keys(target=pane_id, keys="echo PLAIN_OK", enter=True)
        await asyncio.sleep(1.0)
        text = json.loads(await tmux_read_pane(target=pane_id, lines=40))["text"]
        assert "PLAIN_OK" in text
    finally:
        await tmux_kill_session("cm_normal")


@pytest.mark.asyncio
async def test_guard_ignores_unresolvable_target(tmux_server):
    """A bad target is the real command's error to report, not the guard's."""
    await assert_pane_writable("%99999")  # must not raise
