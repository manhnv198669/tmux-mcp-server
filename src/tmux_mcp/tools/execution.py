"""Tmux async command execution tools using pipe-pane and wait-for mechanisms."""

import json

from tmux_mcp.core.errors import PaneBusyError, TmuxError
from tmux_mcp.exec.engine import poll_or_wait_record, run_command_engine, stop_pipe_pane
from tmux_mcp.exec.registry import get_registry
from tmux_mcp.tools.panes import tmux_send_special_key


async def tmux_run_command(
    target: str = "",
    command: str = "",
    timeout: float = 30.0,
    wait: bool = True,
) -> str:
    """Run a shell command in a tmux pane with exact exit code and pipe-pane output capture.

    Args:
        target: Target pane ID (e.g. "%0"). Default active pane.
        command: Shell command string to execute.
        timeout: Timeout in seconds to wait if wait=True (default 30.0).
        wait: If True, block until command finishes or times out (default True).

    Returns:
        JSON string of CommandRunModel or error response.
    """
    if not command:
        return json.dumps({"error": "command cannot be empty"})

    try:
        model = await run_command_engine(
            pane_id=target,
            command=command,
            timeout=timeout,
            wait=wait,
        )
        return json.dumps(model.model_dump(), indent=2)
    except PaneBusyError as e:
        return json.dumps(
            {
                "error": f"Target pane '{e.pane_id}' is busy running non-shell process '{e.current_command}'. Use keypress tools (send_keys) instead.",
                "pane_id": e.pane_id,
                "current_command": e.current_command,
            },
            indent=2,
        )
    except (ValueError, TmuxError) as e:
        return json.dumps({"error": str(e)}, indent=2)


async def tmux_get_command_result(command_id: str = "") -> str:
    """Poll status or fetch result of a tracked command execution.

    Args:
        command_id: Command execution ID (e.g. "cmd_123456").

    Returns:
        JSON string of CommandRunModel.
    """
    if not command_id:
        return json.dumps({"error": "command_id required"})

    registry = get_registry()
    await registry.cleanup_expired_async()
    rec = registry.get(command_id)
    if not rec:
        return json.dumps({"error": f"command {command_id} not found"})

    model = await poll_or_wait_record(rec, timeout=0.0)
    return json.dumps(model.model_dump(), indent=2)


async def tmux_wait_command(command_id: str = "", timeout: float = 30.0) -> str:
    """Wait for a running command execution to finish.

    Args:
        command_id: Command execution ID (e.g. "cmd_123456").
        timeout: Maximum seconds to wait (default 30.0).

    Returns:
        JSON string of CommandRunModel.
    """
    if not command_id:
        return json.dumps({"error": "command_id required"})

    registry = get_registry()
    await registry.cleanup_expired_async()
    rec = registry.get(command_id)
    if not rec:
        return json.dumps({"error": f"command {command_id} not found"})

    model = await poll_or_wait_record(rec, timeout=timeout)
    return json.dumps(model.model_dump(), indent=2)


async def tmux_list_commands(target: str = "") -> str:
    """List tracked command executions in current session.

    Args:
        target: Optional filter for a specific pane ID.

    Returns:
        JSON array string of CommandRunModel objects.
    """
    registry = get_registry()
    models = await registry.list_all(pane_id=target)
    return json.dumps([m.model_dump() for m in models], indent=2)


async def tmux_cancel_command(command_id: str = "") -> str:
    """Cancel a running command execution by sending C-c signal and turning off pipe-pane.

    Args:
        command_id: ID of the command execution to cancel (e.g. "cmd_123").

    Returns:
        JSON string response.
    """
    if not command_id:
        return json.dumps({"error": "command_id required"})

    registry = get_registry()
    await registry.cleanup_expired_async()
    rec = registry.get(command_id)
    if not rec:
        return json.dumps({"error": f"command {command_id} not found"})

    # Send C-c to pane to cancel command
    await tmux_send_special_key(target=rec.model.pane_id, key="C-c")

    # Turn off pipe-pane capture stream immediately (Lỗi 3)
    await stop_pipe_pane(rec.model.pane_id)

    rec.model.status = "cancelled"
    return json.dumps(rec.model.model_dump(), indent=2)
