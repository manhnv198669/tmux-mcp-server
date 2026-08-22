"""Core execution engine implementing pipe-pane and wait-for primitives safely."""

import logging
import os
import re
import shlex
import tempfile
import time
import uuid

from tmux_mcp.config import get_config
from tmux_mcp.core import fsops
from tmux_mcp.core.ansi import strip_ansi
from tmux_mcp.core.context import current_host
from tmux_mcp.core.errors import PaneBusyError, TmuxError, TmuxNotRunningError
from tmux_mcp.core.formats import make_sentinel, parse_line, unescape_tmux_value
from tmux_mcp.core.models import CommandRunModel
from tmux_mcp.core.runner import run_tmux
from tmux_mcp.exec.history import record_finished, record_started
from tmux_mcp.exec.registry import CommandRecord, get_registry
from tmux_mcp.exec.shells import build_epilogue

logger = logging.getLogger(__name__)

ALLOWED_SHELLS = {
    "zsh",
    "bash",
    "fish",
    "sh",
    "dash",
    "ksh",
    "ash",
}

_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9/._-]+$")

# Any command's boundary marker, not only the one being extracted.
_MARKER_LINE_RE = re.compile(r"^__TMUX_MCP_(?:START|END)_[A-Za-z0-9_]+__$")

MAX_OUTPUT_BYTES = 10 * 1024 * 1024  # 10MB cap
MAX_OUTPUT_LINES = 100000  # Cap at 100,000 lines to support 50,000+ line benchmark tests


def extract_clean_output(
    raw_text: str, cmd_id: str, assume_partial: bool = False
) -> tuple[str, bool]:
    """Extract clean command output between start and end markers.

    Returns:
        tuple of (clean_text: str, truncated: bool)

    3 Branches:
    1. Both start_marker and end_marker exist as exact lines:
        Return lines between start_marker and end_marker.
    2. start_marker exists as exact line, but end_marker does NOT exist:
        Return lines from start_marker to end of log (partial output while running/timed out).
    3. start_marker does NOT exist:
        Return empty string "" (command hasn't executed yet or prompt log).
    """
    clean_text = strip_ansi(raw_text)
    start_marker = f"__TMUX_MCP_START_{cmd_id}__"
    end_marker = f"__TMUX_MCP_END_{cmd_id}__"

    lines = clean_text.splitlines()
    start_idx = -1
    end_idx = -1

    for idx, line in enumerate(lines):
        if line.strip() == start_marker:
            start_idx = idx
        elif line.strip() == end_marker and start_idx != -1:
            end_idx = idx
            break

    body_lines: list[str] = []
    forced_truncated = False
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        # Branch 1: Both markers present
        body_lines = lines[start_idx + 1 : end_idx]
    elif start_idx != -1 and end_idx == -1:
        # Branch 2: Start marker present, end marker missing (partial output)
        body_lines = lines[start_idx + 1 :]
    elif assume_partial:
        # Branch 4: the capture was read from its tail, so a missing start marker
        # means the command's first lines fell outside the window rather than that
        # it never ran. Returning "" here would read as "printed nothing", so hand
        # back what survived -- minus any marker line, including one belonging to a
        # neighbouring command -- and say plainly that it was cut.
        body_lines = [line for line in lines if not _MARKER_LINE_RE.match(line.strip())]
        forced_truncated = True
    else:
        # Branch 3: Start marker not reached yet
        return ("", False)

    truncated = forced_truncated
    if len(body_lines) > MAX_OUTPUT_LINES:
        body_lines = body_lines[-MAX_OUTPUT_LINES:]
        truncated = True

    result_text = "\n".join(body_lines).rstrip("\r\n")
    if len(result_text) > MAX_OUTPUT_BYTES:
        result_text = result_text[-MAX_OUTPUT_BYTES:]
        truncated = True

    return (result_text, truncated)


async def stop_pipe_pane(pane_id: str) -> None:
    """Turn off pipe-pane capture stream for target pane."""
    if not pane_id:
        return
    try:
        await run_tmux(["pipe-pane", "-t", pane_id])
    except TmuxNotRunningError:
        # Server gone: the capture stream died with it, nothing left to stop.
        logger.debug("tmux server not running while stopping pipe-pane on %s", pane_id)
    except TmuxError as e:
        # Pane may have been killed already. Log it — a silent failure here leaks
        # a `cat >>` process writing to a temp file for the life of the server.
        logger.warning("Failed to stop pipe-pane on %s: %s", pane_id, e)


async def run_command_engine(
    pane_id: str = "",
    command: str = "",
    timeout: float = 30.0,
    wait: bool = True,
) -> CommandRunModel:
    """Execute command in target pane using pipe-pane + wait-for mechanism.

    Args:
        pane_id: Target pane ID (e.g. "%0"). Default active pane.
        command: Command string to execute.
        timeout: Maximum seconds to wait if wait=True (default 30.0).
        wait: If True, block until command completes or timeout expires.

    Returns:
        CommandRunModel containing execution results and status.
    """
    # Reject multiline commands
    if "\n" in command or "\r" in command:
        raise ValueError("Multiline commands containing newlines are not allowed in run_command. Use single-line commands or heredocs.")

    # 1. Fetch pane info to inspect current foreground process directly using dynamic sentinel
    target_pane = pane_id or "%0"
    sep_info = make_sentinel()
    # pane_current_path rides along on this existing query: the history log wants the
    # directory the command actually ran in, and asking now costs no extra round-trip.
    raw_info = await run_tmux(
        [
            "list-panes",
            "-F",
            f"#{{pane_id}}{sep_info}#{{pane_current_command}}{sep_info}#{{pane_dead}}"
            f"{sep_info}#{{pane_current_path}}",
            "-t",
            target_pane,
        ]
    )

    matched_pane = False
    cwd = ""
    resolved_pane = ""
    for line in raw_info.splitlines():
        fields = parse_line(line, sep_info, expected_fields=4)
        if len(fields) >= 2:
            pid_str, curr_cmd_str = fields[0], fields[1]
            is_dead = fields[2] == "1" if len(fields) >= 3 else False
            if target_pane.startswith("%") and pid_str != target_pane:
                continue
            matched_pane = True
            resolved_pane = pid_str
            cwd = unescape_tmux_value(fields[3]) if len(fields) >= 4 else ""
            if is_dead:
                raise PaneBusyError(target_pane, "dead pane")
            curr_cmd = curr_cmd_str.lower().strip()
            if not curr_cmd or curr_cmd not in ALLOWED_SHELLS:
                raise PaneBusyError(target_pane, curr_cmd or "empty/unknown process")
            break

    if not matched_pane:
        raise TmuxError(["list-panes"], 1, f"Pane {target_pane} not found")

    # 2. Setup command ID and temporary storage
    cmd_id = f"cmd_{uuid.uuid4().hex[:12]}"
    cfg_tmp = get_config()
    host = current_host()
    base_dir = cfg_tmp.remote_tmp_dir if host else tempfile.gettempdir()
    tmp_dir = os.path.join(base_dir, f"tmux-mcp-{cmd_id}")

    if not _SAFE_PATH_RE.match(tmp_dir):
        raise ValueError(f"Unsafe temporary directory path generated: {tmp_dir}")

    await fsops.make_dir(tmp_dir)

    cap_file = os.path.join(tmp_dir, "cap.log")
    rc_file = os.path.join(tmp_dir, "rc.txt")
    channel = f"tmux-mcp-wait-{cmd_id}"

    await fsops.touch(cap_file)

    # 3. Start capture stream via pipe-pane safely with shlex.quote (Blocker 3)
    safe_cap_file = shlex.quote(cap_file)
    await run_tmux(["pipe-pane", "-O", "-t", target_pane, f"cat >> {safe_cap_file}"])

    # 4. Build command + epilogue with start/end markers
    cfg = get_config()
    full_cmd = build_epilogue(
        command,
        rc_file,
        channel,
        cmd_id=cmd_id,
        shell_type=cfg.shell_type,
        remote=bool(current_host()),
    )

    # 5. Create initial model and register
    model = CommandRunModel(
        command_id=cmd_id,
        pane_id=target_pane,
        command=command,
        status="running",
        exit_code=-1,
        output="",
        truncated=False,
        created_at=time.time(),
    )
    registry = get_registry()
    await registry.cleanup_expired_async()
    registry.register(model, tmp_dir, channel, cap_file, rc_file, cwd=cwd, pane=resolved_pane)

    # 6. Send command to pane
    await run_tmux(["send-keys", "-t", target_pane, "-l", "--", full_cmd])
    await run_tmux(["send-keys", "-t", target_pane, "Enter"])

    # Logged at dispatch rather than at completion, so `tail -f` on the history file
    # shows work in flight instead of only what has already finished.
    record_started(model, cwd=cwd, pane=resolved_pane)

    if not wait:
        return model

    # 7. Wait for completion if wait=True
    rec = registry.get(cmd_id)
    if not rec:
        return model

    return await poll_or_wait_record(rec, timeout=timeout)


async def poll_or_wait_record(rec: CommandRecord, timeout: float = 30.0) -> CommandRunModel:
    """Wait for command completion or poll current state of a record."""
    if rec.model.status in ("completed", "failed", "cancelled"):
        return rec.model

    if await fsops.exists_nonempty(rec.rc_file):
        return await finalize_record(rec)

    if timeout <= 0:
        return await _update_running_record(rec)

    try:
        await run_tmux(["wait-for", rec.channel], timeout=timeout)
        return await finalize_record(rec)
    except (TimeoutError, TmuxError):
        if await fsops.exists_nonempty(rec.rc_file):
            return await finalize_record(rec)
        return await _update_running_record(rec)


async def finalize_record(rec: CommandRecord) -> CommandRunModel:
    """Finalize command record upon completion and turn off pipe-pane."""
    await stop_pipe_pane(rec.model.pane_id)

    exit_code = 0
    try:
        content = (await fsops.read_text(rec.rc_file)).strip()
        if content.lstrip("-").isdigit():
            exit_code = int(content)
    except OSError as e:
        logger.warning("Could not read exit code file %s: %s", rec.rc_file, e)

    output_text = ""
    truncated = False
    try:
        raw_text = await fsops.read_text(rec.cap_file, max_bytes=MAX_OUTPUT_BYTES * 2)
        assume_partial = len(raw_text) >= MAX_OUTPUT_BYTES * 2
        output_text, truncated = extract_clean_output(
            raw_text, rec.model.command_id, assume_partial=assume_partial
        )
    except OSError as e:
        logger.warning("Could not read capture file %s: %s", rec.cap_file, e)

    rec.model.exit_code = exit_code
    rec.model.status = "completed" if exit_code == 0 else "failed"
    rec.model.output = output_text
    rec.model.truncated = truncated

    # poll_or_wait_record returns early once the status is terminal, so this runs
    # exactly once per command no matter how often the caller polls.
    record_finished(rec.model, cwd=rec.cwd, pane=rec.pane)
    return rec.model


async def _update_running_record(rec: CommandRecord) -> CommandRunModel:
    """Update running record with current partial output."""
    output_text = ""
    truncated = False
    try:
        raw_text = await fsops.read_text(rec.cap_file, max_bytes=MAX_OUTPUT_BYTES * 2)
        assume_partial = len(raw_text) >= MAX_OUTPUT_BYTES * 2
        output_text, truncated = extract_clean_output(
            raw_text, rec.model.command_id, assume_partial=assume_partial
        )
    except OSError as e:
        logger.warning("Could not read capture file %s: %s", rec.cap_file, e)

    rec.model.output = output_text
    rec.model.truncated = truncated
    return rec.model
