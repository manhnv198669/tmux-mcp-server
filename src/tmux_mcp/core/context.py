"""The host a single call is aimed at, as opposed to the server's default."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

from tmux_mcp.config import get_config

remote_host_var: ContextVar[str] = ContextVar("tmux_mcp_remote_host", default="")


def current_host() -> str:
    """Host for the call in flight: the per-call host, else the instance default."""
    per_call = remote_host_var.get()
    if per_call:
        return per_call
    return get_config().remote_host


@contextmanager
def use_host(host: str) -> Generator[None]:
    """Aim every tmux call inside this block at `host` ("" means local)."""
    token = remote_host_var.set(host)
    try:
        yield
    finally:
        remote_host_var.reset(token)
