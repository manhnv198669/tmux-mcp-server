"""Command registry with TTL and LRU eviction for tracked executions."""

from dataclasses import dataclass
import logging
import os
import shutil
import time
from typing import Dict, Optional

from tmux_mcp.core.errors import TmuxError, TmuxNotRunningError
from tmux_mcp.core.models import CommandRunModel
from tmux_mcp.core.runner import run_tmux

logger = logging.getLogger(__name__)


@dataclass
class CommandRecord:
    model: CommandRunModel
    tmp_dir: str
    channel: str
    cap_file: str
    rc_file: str
    last_accessed: float


class CommandRegistry:
    """In-memory store for command execution states."""

    def __init__(self, max_entries: int = 500, ttl_seconds: float = 3600.0):
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._records: Dict[str, CommandRecord] = {}

    def register(
        self,
        model: CommandRunModel,
        tmp_dir: str,
        channel: str,
        cap_file: str,
        rc_file: str,
    ) -> None:
        rec = CommandRecord(
            model=model,
            tmp_dir=tmp_dir,
            channel=channel,
            cap_file=cap_file,
            rc_file=rc_file,
            last_accessed=time.time(),
        )
        self._records[model.command_id] = rec

    def get(self, command_id: str) -> Optional[CommandRecord]:
        rec = self._records.get(command_id)
        if rec:
            rec.last_accessed = time.time()
        return rec

    async def list_all(self, pane_id: str = "") -> list[CommandRunModel]:
        await self.cleanup_expired_async()
        results: list[CommandRunModel] = []
        for rec in self._records.values():
            if not pane_id or rec.model.pane_id == pane_id:
                results.append(rec.model)
        return results

    async def cleanup_expired_async(self) -> None:
        now = time.time()
        expired_ids = [
            cid
            for cid, rec in self._records.items()
            if (now - rec.model.created_at) > self.ttl_seconds
        ]
        for cid in expired_ids:
            await self._remove_async(cid)
        await self._enforce_lru_async()

    async def _enforce_lru_async(self) -> None:
        if len(self._records) <= self.max_entries:
            return
        sorted_records = sorted(self._records.items(), key=lambda item: item[1].last_accessed)
        to_remove = len(self._records) - self.max_entries
        for cid, _ in sorted_records[:to_remove]:
            await self._remove_async(cid)

    async def _remove_async(self, command_id: str) -> None:
        rec = self._records.pop(command_id, None)
        if rec:
            try:
                await run_tmux(["pipe-pane", "-t", rec.model.pane_id])
            except TmuxNotRunningError:
                logger.debug(
                    "tmux server not running while evicting %s", rec.model.command_id
                )
            except TmuxError as e:
                logger.warning(
                    "Failed to stop pipe-pane while evicting %s: %s",
                    rec.model.command_id,
                    e,
                )
            if rec.tmp_dir and os.path.exists(rec.tmp_dir):
                try:
                    shutil.rmtree(rec.tmp_dir, ignore_errors=True)
                except OSError as e:
                    logger.warning("Could not remove temp dir %s: %s", rec.tmp_dir, e)


_global_registry = CommandRegistry()


def get_registry() -> CommandRegistry:
    return _global_registry
