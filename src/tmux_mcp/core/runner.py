"""Async tmux command runner.

NO shell=True is ever used here or anywhere in tmux-mcp.
All tmux commands pass through this module as explicit argv lists.
"""

import asyncio
from asyncio.subprocess import PIPE
import logging
import uuid

from tmux_mcp.config import get_config
from tmux_mcp.core.errors import TmuxError, TmuxNotRunningError

logger = logging.getLogger(__name__)


def get_socket_args(override_socket_name: str = "", override_socket_path: str = "") -> list[str]:
    """Determine socket flags (-L or -S) for tmux execution."""
    sock_name = override_socket_name or get_config().socket_name
    sock_path = override_socket_path or get_config().socket_path

    if sock_name:
        return ["-L", sock_name]
    elif sock_path:
        return ["-S", sock_path]
    return []


async def run_tmux(
    args: list[str],
    *,
    timeout: float = 10.0,
    override_socket_name: str = "",
    override_socket_path: str = "",
) -> str:
    """Execute a single tmux command via argv list (never shell=True).

    Raises:
        TmuxError: If tmux returns non-zero status.
        TmuxNotRunningError: If server/socket is not running.
    """
    socket_flags = get_socket_args(override_socket_name, override_socket_path)
    argv = ["tmux", *socket_flags, *args]

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=PIPE,
            stderr=PIPE,
        )
    except FileNotFoundError:
        raise TmuxNotRunningError("tmux binary not found in PATH")

    try:
        out_bytes, err_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            # Process already exited between the timeout and the kill; nothing to reap.
            logger.debug("tmux process %s already gone when killing after timeout", proc.pid)
        except OSError as e:
            logger.warning("Failed to kill timed-out tmux process %s: %s", proc.pid, e)
        raise TmuxError(argv, -1, f"Execution timed out after {timeout}s")

    stdout = out_bytes.decode(errors="replace")
    stderr = err_bytes.decode(errors="replace")

    if proc.returncode != 0:
        # Check if error is due to server not running
        if "no server running" in stderr or "error connecting to" in stderr:
            raise TmuxNotRunningError(" ".join(socket_flags) or "default")
        raise TmuxError(argv, proc.returncode, stderr)

    return stdout


async def run_tmux_batch(
    commands: list[list[str]],
    *,
    timeout: float = 10.0,
    override_socket_name: str = "",
    override_socket_path: str = "",
) -> list[str]:
    """Execute multiple tmux commands in a single subprocess invocation.

    tmux commands are chained with ';' and separated by sentinel markers.
    """
    if not commands:
        return []

    sentinel_prefix = f"__TMUX_MCP_SENTINEL_{uuid.uuid4().hex}__"
    batched_args: list[str] = []

    for idx, cmd in enumerate(commands):
        if idx > 0:
            batched_args.append(";")
        batched_args.extend(cmd)
        batched_args.extend([";", "display-message", "-p", f"{sentinel_prefix}{idx}"])

    raw_output = await run_tmux(
        batched_args,
        timeout=timeout,
        override_socket_name=override_socket_name,
        override_socket_path=override_socket_path,
    )

    # Split by sentinels
    results: list[str] = []
    current_chunk: list[str] = []

    for line in raw_output.splitlines():
        if sentinel_prefix in line:
            results.append("\n".join(current_chunk))
            current_chunk = []
        else:
            current_chunk.append(line)

    return results
