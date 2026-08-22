"""Resolve the tmux server's configured prefix key dynamically."""

from tmux_mcp.core.runner import run_tmux


async def resolve_prefix() -> str:
    """Return the tmux server's configured prefix key, e.g. "C-b" or "C-t"."""
    raw = await run_tmux(["show-options", "-gv", "prefix"])
    prefix = raw.strip()

    if not prefix or prefix == "none":
        raise ValueError("tmux server has no prefix key configured (prefix is unset or 'none')")

    return prefix