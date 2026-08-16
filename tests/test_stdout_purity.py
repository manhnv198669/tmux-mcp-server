"""Test stdout purity (Rule 2 / R7 / Test #9).

Verifies that the server subprocess ONLY outputs valid JSON-RPC lines on stdout.
Any stray print() or library output to stdout fails the test.
"""

import asyncio
import json
import sys
from asyncio.subprocess import PIPE

import pytest


@pytest.mark.asyncio
async def test_stdout_purity_on_initialize():
    cmd = [sys.executable, "-m", "tmux_mcp", "--log-level=DEBUG"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE,
    )

    # Standard MCP JSON-RPC initialize request
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }

    req_bytes = (json.dumps(init_request) + "\n").encode("utf-8")

    try:
        proc.stdin.write(req_bytes)
        await proc.stdin.drain()
        await asyncio.sleep(0.5)
    except Exception:
        pass

    proc.terminate()
    stdout_bytes, _stderr_bytes = await proc.communicate()

    stdout_str = stdout_bytes.decode("utf-8", errors="replace")

    # Every non-empty line in stdout must be valid JSON
    for line in stdout_str.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            assert "jsonrpc" in data or "id" in data or "result" in data
        except json.JSONDecodeError:
            pytest.fail(f"Stray output detected on stdout (corrupts MCP stdio transport): {line!r}")
