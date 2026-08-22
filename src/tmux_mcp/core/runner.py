"""Async tmux command runner.

NO shell=True is ever used here or anywhere in tmux-mcp.
All tmux commands pass through this module as explicit argv lists.
"""

import asyncio
import fnmatch
import logging
import shlex
import uuid
from asyncio.subprocess import PIPE

from tmux_mcp.config import get_config
from tmux_mcp.core.context import current_host
from tmux_mcp.core.errors import RemoteConnectionError, TmuxError, TmuxNotRunningError

logger = logging.getLogger(__name__)


def get_socket_args(override_socket_name: str = "", override_socket_path: str = "") -> list[str]:
    """Determine socket flags (-L or -S) for tmux execution."""
    if override_socket_name:
        return ["-L", override_socket_name]
    if override_socket_path:
        return ["-S", override_socket_path]

    host = current_host()
    if host:
        cfg = get_config()
        for pattern, value in cfg.host_sockets.items():
            if fnmatch.fnmatch(host, pattern):
                if value.startswith("/"):
                    return ["-S", value]
                return ["-L", value]

    sock_name = get_config().socket_name
    sock_path = get_config().socket_path

    if sock_name:
        return ["-L", sock_name]
    elif sock_path:
        return ["-S", sock_path]
    return []


def build_argv(tmux_args: list[str], socket_flags: list[str]) -> list[str]:
    """Return the argv to execute: local tmux, or ssh-wrapped tmux when configured.

    Remote mode requires BatchMode=yes: without it a host needing a password
    blocks forever instead of failing fast. Every argument goes through
    shlex.quote because tmux format strings contain #{...}, ';' separators and
    \\x1f sentinels the remote shell would otherwise mangle.
    """
    cfg = get_config()
    host = current_host()
    if not host:
        return ["tmux", *socket_flags, *tmux_args]

    remote_cmd = " ".join(shlex.quote(a) for a in ["tmux", *socket_flags, *tmux_args])
    return ["ssh", "-o", "BatchMode=yes", *cfg.remote_ssh_opts, host, remote_cmd]


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
        RemoteConnectionError: When remote and ssh itself fails (exit 255).
    """
    cfg = get_config()
    host = current_host()
    is_remote = bool(host)
    socket_flags = get_socket_args(override_socket_name, override_socket_path)
    argv = build_argv(args, socket_flags)

    # Remote execution pays network cost on every round trip; fold it into the
    # effective timeout without changing the caller-visible signature.
    effective_timeout = timeout + (cfg.remote_ssh_overhead if is_remote else 0.0)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=PIPE,
            stderr=PIPE,
        )
    except FileNotFoundError as e:
        # In remote mode argv[0] is ssh, so naming tmux here would send the reader
        # looking for the wrong missing binary.
        raise TmuxNotRunningError(f"{argv[0]} binary not found in PATH") from e

    try:
        out_bytes, err_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=effective_timeout
        )
    except TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            # Process already exited between the timeout and the kill; nothing to reap.
            logger.debug("tmux process %s already gone when killing after timeout", proc.pid)
        except OSError as e:
            logger.warning("Failed to kill timed-out tmux process %s: %s", proc.pid, e)
        raise TmuxError(argv, -1, f"Execution timed out after {timeout}s") from None

    stdout = out_bytes.decode(errors="replace")
    stderr = err_bytes.decode(errors="replace")

    if proc.returncode != 0:
        # ssh itself failed (exit 255), as opposed to the remote tmux failing.
        if proc.returncode == 255 and is_remote:
            raise RemoteConnectionError(host, stderr)
        # The remote tmux's stderr comes back through ssh unchanged, so the
        # same detection works in both modes.
        # Check if error is due to server not running
        if "no server running" in stderr or "error connecting to" in stderr:
            raise TmuxNotRunningError(" ".join(socket_flags) or "default")
        raise TmuxError(argv, proc.returncode, stderr)

    return stdout


async def run_remote_shell(cmdline: str, *, timeout: float = 15.0) -> str:
    """Run an arbitrary shell command line on the configured remote host."""
    cfg = get_config()
    host = current_host()
    if not host:
        raise RuntimeError("remote_host is not configured")
    argv = ["ssh", "-o", "BatchMode=yes", *cfg.remote_ssh_opts, host, cmdline]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=PIPE,
            stderr=PIPE,
        )
    except FileNotFoundError as e:
        raise TmuxNotRunningError(f"{argv[0]} binary not found in PATH") from e

    try:
        out_bytes, err_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            logger.debug("remote shell process %s already gone when killing after timeout", proc.pid)
        except OSError as e:
            logger.warning("Failed to kill timed-out remote shell process %s: %s", proc.pid, e)
        raise TmuxError(argv, -1, f"Execution timed out after {timeout}s") from None

    stdout = out_bytes.decode(errors="replace")
    stderr = err_bytes.decode(errors="replace")

    if proc.returncode != 0:
        if proc.returncode == 255:
            raise RemoteConnectionError(host, stderr)
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
