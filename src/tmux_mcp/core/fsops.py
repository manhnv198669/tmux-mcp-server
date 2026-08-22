"""Async filesystem facade that works locally or over ssh."""

import logging
import os
import shlex
import shutil

from tmux_mcp.core.context import current_host
from tmux_mcp.core.errors import TmuxError
from tmux_mcp.core.runner import run_remote_shell

logger = logging.getLogger(__name__)


async def make_dir(path: str) -> None:
    """Ensure directory exists."""
    if not current_host():
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            logger.warning("make_dir failed for %s: %s", path, e)
        return
    try:
        await run_remote_shell(f"mkdir -p {shlex.quote(path)}")
    except (TmuxError, OSError) as e:
        logger.warning("make_dir failed for %s: %s", path, e)


async def touch(path: str) -> None:
    """Create empty file if it does not exist."""
    if not current_host():
        try:
            open(path, "a").close()
        except OSError as e:
            logger.warning("touch failed for %s: %s", path, e)
        return
    try:
        await run_remote_shell(f": >> {shlex.quote(path)}")
    except (TmuxError, OSError) as e:
        logger.warning("touch failed for %s: %s", path, e)


async def exists_nonempty(path: str) -> bool:
    """Return True if path exists and is non-empty."""
    if not current_host():
        try:
            return os.path.exists(path) and os.path.getsize(path) > 0
        except OSError as e:
            logger.warning("exists_nonempty failed for %s: %s", path, e)
            return False
    try:
        await run_remote_shell(f"test -s {shlex.quote(path)}")
    except TmuxError:
        return False
    except OSError as e:
        logger.warning("exists_nonempty failed for %s: %s", path, e)
        return False
    return True


async def read_text(path: str, max_bytes: int = 0) -> str:
    """Read file contents; return last max_bytes bytes when requested."""
    if not current_host():
        try:
            with open(path, "rb") as f:
                data = f.read()
            if max_bytes > 0 and len(data) > max_bytes:
                data = data[-max_bytes:]
            return data.decode(errors="replace")
        except OSError as e:
            logger.warning("read_text failed for %s: %s", path, e)
            return ""
    try:
        if max_bytes > 0:
            cmd = f"tail -c {max_bytes} {shlex.quote(path)}"
        else:
            cmd = f"cat {shlex.quote(path)}"
        return await run_remote_shell(cmd)
    except TmuxError:
        return ""
    except OSError as e:
        logger.warning("read_text failed for %s: %s", path, e)
        return ""


async def remove_tree(path: str) -> None:
    """Remove directory tree."""
    if not current_host():
        try:
            shutil.rmtree(path, ignore_errors=False)
        except OSError as e:
            logger.warning("remove_tree failed for %s: %s", path, e)
        return
    try:
        await run_remote_shell(f"rm -rf {shlex.quote(path)}")
    except (TmuxError, OSError) as e:
        logger.warning("remove_tree failed for %s: %s", path, e)
