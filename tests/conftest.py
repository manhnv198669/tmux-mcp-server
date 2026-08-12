"""Pytest fixtures for tmux-mcp tests.

CRITICAL SAFETY RULE:
Tests MUST ONLY use isolated test sockets (e.g. -L tmux-mcp-test).
NEVER execute tmux kill-server or manipulate sessions on the default socket.
"""

import asyncio
from typing import AsyncGenerator
import pytest
import pytest_asyncio

from tmux_mcp.config import Config, set_config
from tmux_mcp.core.runner import run_tmux

TEST_SOCKET = "tmux-mcp-test"


@pytest.fixture(autouse=True)
def configure_test_config():
    """Ensure global config uses test socket for all tests."""
    cfg = Config(socket_name=TEST_SOCKET, tool_profile="full")
    set_config(cfg)
    return cfg


@pytest_asyncio.fixture
async def tmux_server() -> AsyncGenerator[str, None]:
    """Start an isolated tmux server on TEST_SOCKET and tear down when done."""
    # Ensure any residual test server is cleaned up on test socket ONLY
    try:
        await run_tmux(["kill-server"], override_socket_name=TEST_SOCKET)
    except Exception:
        pass

    # Start a dummy detached session on the test socket
    await run_tmux(["new-session", "-d", "-s", "test_session_0"], override_socket_name=TEST_SOCKET)
    await asyncio.sleep(0.8)

    yield TEST_SOCKET

    # Clean up test socket server ONLY
    try:
        await run_tmux(["kill-server"], override_socket_name=TEST_SOCKET)
    except Exception:
        pass
