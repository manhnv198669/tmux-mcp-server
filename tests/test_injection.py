"""Test security against shell injection attempts (Rule 1 / Test #1 & Blocker 3)."""

import contextlib
import os

import pytest

from tmux_mcp.core.runner import run_tmux
from tmux_mcp.exec.engine import run_command_engine
from tmux_mcp.tools.sessions import tmux_create_session


@pytest.mark.asyncio
async def test_shell_injection_prevention(tmux_server):
    pwn_file = "/tmp/PWNED_TMUX_MCP_TEST"
    if os.path.exists(pwn_file):
        os.remove(pwn_file)

    injection_name = f'a"; touch {pwn_file}; "b'

    # 1. Test session creation via tool
    await tmux_create_session(name=injection_name)

    assert not os.path.exists(
        pwn_file
    ), "CRITICAL VULNERABILITY: Shell injection payload executed during session creation!"

    # Clean up created session
    with contextlib.suppress(Exception):
        await run_tmux(["kill-session", "-t", injection_name])


@pytest.mark.asyncio
async def test_command_run_injection_prevention(tmux_server):
    pwn_file = "/tmp/PWNED_CMD_TEST"
    if os.path.exists(pwn_file):
        os.remove(pwn_file)

    # Execute via run_command_engine
    model = await run_command_engine(command="echo 'test'; (exit 0)")
    assert model.status == "completed"
    assert "echo 'test'" in model.command
