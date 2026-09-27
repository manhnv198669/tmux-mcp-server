"""Large-payload delivery for send_keys.

`send-keys -l` puts the whole payload on the tmux command line, which tmux caps
at 16KB. These tests pin the size-aware path that replaces it.
"""

import asyncio
import json
import sys
import textwrap

import pytest

from tmux_mcp.core.errors import TmuxError
from tmux_mcp.core.keys import _chunk, send_literal_text
from tmux_mcp.core.runner import run_tmux
from tmux_mcp.tools.panes import tmux_send_keys

# Past tmux's ~16,300-byte command-line ceiling: `send-keys -l` fails outright here.
OVERSIZED = 20000

RAW_READER = textwrap.dedent(
    """
    import os, sys, termios, tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    sys.stdout.write("\\x1b[?2004h")   # request bracketed paste
    sys.stdout.flush()
    out = open(sys.argv[1], "wb", buffering=0)
    try:
        while True:
            b = os.read(fd, 4096)
            if not b:
                break
            if b"\\x04" in b:
                out.write(b.split(b"\\x04")[0])
                break
            out.write(b)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    """
)


@pytest.fixture
def raw_reader(tmp_path):
    """A pane running a raw-mode reader that logs every byte it receives.

    Raw mode matters: a canonical-mode reader (`cat`) is capped at MAX_CANON
    (1024 bytes) per line by the line discipline, which would mask the behaviour
    under test with a kernel limit no delivery method can beat.
    """
    script = tmp_path / "raw_reader.py"
    script.write_text(RAW_READER)
    return script, tmp_path / "received.bin"


async def _drain(target, sink, expected_bytes):
    deadline = asyncio.get_running_loop().time() + 30.0
    while asyncio.get_running_loop().time() < deadline:
        if sink.exists() and sink.stat().st_size >= expected_bytes:
            break
        await asyncio.sleep(0.2)
    await run_tmux(["send-keys", "-t", target, "-l", "--", "\x04"])
    await asyncio.sleep(0.5)
    return sink.read_bytes() if sink.exists() else b""


def test_chunk_never_splits_a_character():
    text = "é" * 10
    chunks = _chunk(text, 3)
    assert "".join(chunks) == text
    assert all(len(c.encode()) <= 3 for c in chunks)


@pytest.mark.asyncio
async def test_send_keys_rejects_oversized_payload_via_plain_send_keys(tmux_server):
    """The limit being worked around is real, not hypothetical."""
    with pytest.raises(TmuxError, match="too long"):
        await run_tmux(["send-keys", "-t", "test_session_0", "-l", "--", "a" * OVERSIZED])


@pytest.mark.asyncio
async def test_short_text_still_uses_send_keys(tmux_server):
    result = json.loads(await tmux_send_keys(target="test_session_0", keys="echo hi"))
    assert result["method"] == "keys"


@pytest.mark.asyncio
async def test_oversized_payload_arrives_intact(tmux_server, raw_reader):
    script, sink = raw_reader
    await run_tmux(
        ["new-window", "-P", "-F", "#{pane_id}", sys.executable, str(script), str(sink)]
    )
    pane = (await run_tmux(["display-message", "-p", "#{pane_id}"])).strip()
    await asyncio.sleep(1.0)

    payload = "".join(chr(97 + (i % 26)) for i in range(OVERSIZED))
    result = json.loads(await tmux_send_keys(target=pane, keys=payload))
    assert result["method"] == "paste"

    received = await _drain(pane, sink, OVERSIZED)
    body = received.replace(b"\x1b[200~", b"").replace(b"\x1b[201~", b"")
    assert body.decode() == payload


@pytest.mark.asyncio
async def test_paste_is_bracketed_and_enter_lands_after_it(tmux_server, raw_reader):
    """A TUI must see one paste event, then a separate Enter that submits it."""
    script, sink = raw_reader
    await run_tmux(
        ["new-window", "-P", "-F", "#{pane_id}", sys.executable, str(script), str(sink)]
    )
    pane = (await run_tmux(["display-message", "-p", "#{pane_id}"])).strip()
    await asyncio.sleep(1.0)

    payload = "line one\nline two"
    await tmux_send_keys(target=pane, keys=payload, enter=True, paste=True)

    received = await _drain(pane, sink, len(payload))
    assert b"\x1b[200~" in received
    # The Enter must not be swallowed into the paste, or the TUI never submits.
    assert received.split(b"\x1b[201~")[1] == b"\r"


@pytest.mark.asyncio
async def test_failed_paste_leaves_no_buffer_behind(tmux_server):
    before = await run_tmux(["list-buffers"])
    with pytest.raises(TmuxError):
        await send_literal_text("%nonexistent-pane", "x" * 500)
    assert (await run_tmux(["list-buffers"])) == before


@pytest.mark.asyncio
async def test_successful_paste_leaves_no_buffer_behind(tmux_server):
    before = await run_tmux(["list-buffers"])
    await send_literal_text("test_session_0", "x" * 500)
    await asyncio.sleep(0.3)
    assert (await run_tmux(["list-buffers"])) == before


@pytest.mark.asyncio
async def test_chunked_fallback_delivers_everything(tmux_server, raw_reader, monkeypatch):
    """Old tmux builds without `load-buffer -` fall back to chunked send-keys."""
    script, sink = raw_reader
    await run_tmux(
        ["new-window", "-P", "-F", "#{pane_id}", sys.executable, str(script), str(sink)]
    )
    pane = (await run_tmux(["display-message", "-p", "#{pane_id}"])).strip()
    await asyncio.sleep(1.0)

    from tmux_mcp.core import keys as keys_mod

    real_run_tmux = keys_mod.run_tmux

    async def fake_run_tmux(args, **kwargs):
        if args and args[0] == "load-buffer":
            raise TmuxError(args, 1, "unknown flag")
        return await real_run_tmux(args, **kwargs)

    monkeypatch.setattr(keys_mod, "run_tmux", fake_run_tmux)
    monkeypatch.setattr(keys_mod, "CHUNK_BYTES", 512)

    payload = "".join(chr(97 + (i % 26)) for i in range(5000))
    assert await send_literal_text(pane, payload) == "chunked"

    received = await _drain(pane, sink, len(payload))
    assert received.decode() == payload
