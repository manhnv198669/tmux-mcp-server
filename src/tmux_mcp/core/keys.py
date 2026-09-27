"""Literal text delivery into a pane.

`send-keys -l` carries the whole payload as a single argv element, and tmux caps
one client->server command message at 16KB: past roughly 16,300 bytes tmux
refuses the command outright with "command too long", so the text never arrives
at all. Well below that ceiling a full-screen application can still lose part of
a large burst, because the bytes reach it as thousands of undifferentiated
keypresses and a TUI that re-renders between reads processes only some of them.

A paste buffer avoids both problems: `load-buffer -` takes the payload on stdin,
so no argv limit applies, and `paste-buffer -p` wraps it in bracketed-paste
markers whenever the application has asked for them, so the app sees one paste
event instead of a keystroke storm. Applications that never requested bracketed
paste are unaffected -- tmux simply omits the markers.

What this cannot fix: a pane whose foreground process reads the tty in canonical
mode (`cat`, `read`, a password prompt) is limited by the line discipline to
MAX_CANON (1024 bytes) per line, and the kernel discards the rest no matter how
the bytes were delivered.
"""

import logging
import uuid
from contextlib import suppress

from tmux_mcp.config import get_config
from tmux_mcp.core.errors import TmuxError
from tmux_mcp.core.runner import run_tmux

logger = logging.getLogger(__name__)

# Comfortably under tmux's own ~16,300-byte ceiling, leaving room for the rest of
# the command line (socket flags, `-t <target>`, and the ssh quoting in remote mode).
CHUNK_BYTES = 4000


def _send_keys_args(target: str, text: str) -> list[str]:
    args = ["send-keys"]
    if target:
        args.extend(["-t", target])
    args.extend(["-l", "--", text])
    return args


def _chunk(text: str, size: int) -> list[str]:
    """Split on encoded size without ever cutting a character in half."""
    chunks: list[str] = []
    current = ""
    current_len = 0
    for ch in text:
        ch_len = len(ch.encode())
        if current and current_len + ch_len > size:
            chunks.append(current)
            current, current_len = "", 0
        current += ch
        current_len += ch_len
    if current:
        chunks.append(current)
    return chunks


async def send_literal_text(target: str, text: str, *, force_paste: bool = False) -> str:
    """Send literal text to a pane, choosing a delivery that survives its size.

    Args:
        target: Target pane (may be empty for the active pane).
        text: Literal text to deliver; never interpreted as key names.
        force_paste: Use the paste buffer even for a short payload.

    Returns:
        The delivery method actually used: "keys", "paste" or "chunked".
    """
    if not text:
        return "keys"

    data = text.encode()
    if not force_paste and len(data) <= max(get_config().paste_threshold, 0):
        await run_tmux(_send_keys_args(target, text))
        return "keys"

    buffer_name = f"tmux-mcp-{uuid.uuid4().hex}"
    try:
        await run_tmux(["load-buffer", "-b", buffer_name, "-"], input_data=data)
    except TmuxError as e:
        # Old tmux builds without `load-buffer -` (stdin) leave chunking as the only
        # way to stay under the 16KB command limit. It loses the paste markers, so a
        # TUI sees keystrokes again -- correct, just not as robust.
        logger.warning("load-buffer unavailable (%s); falling back to chunked send-keys", e)
        return await _send_chunked(target, text)

    try:
        args = ["paste-buffer", "-p", "-d", "-b", buffer_name]
        if target:
            args.extend(["-t", target])
        await run_tmux(args)
    except BaseException:
        # -d only deletes the buffer on a paste that happened; a failed paste would
        # otherwise leave the payload sitting in the user's buffer stack.
        with suppress(TmuxError):
            await run_tmux(["delete-buffer", "-b", buffer_name])
        raise

    return "paste"


async def _send_chunked(target: str, text: str) -> str:
    for piece in _chunk(text, CHUNK_BYTES):
        await run_tmux(_send_keys_args(target, piece))
    return "chunked"
