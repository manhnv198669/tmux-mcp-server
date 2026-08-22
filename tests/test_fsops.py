"""Tests for filesystem facade local and remote modes."""

import pytest

from tmux_mcp.config import Config, set_config
from tmux_mcp.core import fsops
from tmux_mcp.core.errors import TmuxError


async def _fail_run_remote_shell(*_args, **_kwargs):
    raise AssertionError("run_remote_shell should not be called in local mode")


def test_local_make_dir_creates_nested_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(fsops, "run_remote_shell", _fail_run_remote_shell)
    set_config(Config())
    try:
        nested = str(tmp_path / "a" / "b" / "c")

        async def _run():
            await fsops.make_dir(nested)
            assert (tmp_path / "a" / "b" / "c").is_dir()
            await fsops.make_dir(nested)

        import asyncio

        asyncio.run(_run())
    finally:
        set_config(Config())


def test_local_touch_and_exists_nonempty(tmp_path, monkeypatch):
    monkeypatch.setattr(fsops, "run_remote_shell", _fail_run_remote_shell)
    set_config(Config())
    try:
        p = str(tmp_path / "empty.txt")

        async def _run():
            await fsops.touch(p)
            assert (tmp_path / "empty.txt").exists()
            assert await fsops.exists_nonempty(p) is False
            with open(p, "w") as f:
                f.write("hello")
            assert await fsops.exists_nonempty(p) is True
            assert await fsops.read_text(p) == "hello"

        import asyncio

        asyncio.run(_run())
    finally:
        set_config(Config())


def test_local_read_text_max_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(fsops, "run_remote_shell", _fail_run_remote_shell)
    set_config(Config())
    try:
        p = str(tmp_path / "abcdefgh.txt")
        with open(p, "w") as f:
            f.write("abcdefgh")

        async def _run():
            assert await fsops.read_text(p, max_bytes=3) == "fgh"

        import asyncio

        asyncio.run(_run())
    finally:
        set_config(Config())


def test_local_read_text_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(fsops, "run_remote_shell", _fail_run_remote_shell)
    set_config(Config())
    try:
        p = str(tmp_path / "does-not-exist.txt")

        async def _run():
            assert await fsops.read_text(p) == ""

        import asyncio

        asyncio.run(_run())
    finally:
        set_config(Config())


def test_local_remove_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(fsops, "run_remote_shell", _fail_run_remote_shell)
    set_config(Config())
    try:
        d = str(tmp_path / "to_remove")
        import os

        os.makedirs(d)

        async def _run():
            await fsops.remove_tree(d)
            assert not (tmp_path / "to_remove").exists()
            await fsops.remove_tree(d)

        import asyncio

        asyncio.run(_run())
    finally:
        set_config(Config())


def test_local_none_calls_run_remote_shell(tmp_path, monkeypatch):
    monkeypatch.setattr(fsops, "run_remote_shell", _fail_run_remote_shell)
    set_config(Config())
    try:
        import asyncio
        import os

        async def _run():
            d = str(tmp_path / "x" / "y")
            await fsops.make_dir(d)
            f = str(tmp_path / "x" / "y" / "f.txt")
            await fsops.touch(f)
            assert await fsops.exists_nonempty(f) is False
            with open(f, "w") as fh:
                fh.write("hello")
            assert await fsops.exists_nonempty(f) is True
            assert await fsops.read_text(f) == "hello"
            with open(f, "w") as fh:
                fh.write("abcdefgh")
            assert await fsops.read_text(f, max_bytes=3) == "fgh"
            assert await fsops.read_text(str(tmp_path / "nope")) == ""
            await fsops.remove_tree(str(tmp_path / "x"))
            assert not os.path.exists(str(tmp_path / "x"))

        asyncio.run(_run())
    finally:
        set_config(Config())


@pytest.mark.asyncio
async def test_remote_make_dir_quoting(monkeypatch):
    set_config(Config(remote_host="prod-01"))
    recorded: list[str] = []

    async def fake(cmdline: str, **_kwargs):
        recorded.append(cmdline)
        return ""

    monkeypatch.setattr(fsops, "run_remote_shell", fake)
    try:
        await fsops.make_dir("/tmp/x y")
        assert len(recorded) == 1
        assert "mkdir -p '/tmp/x y'" in recorded[0]
    finally:
        set_config(Config())


@pytest.mark.asyncio
async def test_remote_read_text_with_max_bytes(monkeypatch):
    set_config(Config(remote_host="prod-01"))
    recorded: list[str] = []

    async def fake(cmdline: str, **_kwargs):
        recorded.append(cmdline)
        return "data"

    monkeypatch.setattr(fsops, "run_remote_shell", fake)
    try:
        result = await fsops.read_text("/tmp/a", max_bytes=100)
        assert result == "data"
        assert len(recorded) == 1
        assert "tail -c 100" in recorded[0]
        assert "/tmp/a" in recorded[0]
    finally:
        set_config(Config())


@pytest.mark.asyncio
async def test_remote_read_text_without_max_bytes(monkeypatch):
    set_config(Config(remote_host="prod-01"))
    recorded: list[str] = []

    async def fake(cmdline: str, **_kwargs):
        recorded.append(cmdline)
        return "content"

    monkeypatch.setattr(fsops, "run_remote_shell", fake)
    try:
        result = await fsops.read_text("/tmp/a")
        assert result == "content"
        assert len(recorded) == 1
        assert "cat" in recorded[0]
        assert "/tmp/a" in recorded[0]
    finally:
        set_config(Config())


@pytest.mark.asyncio
async def test_remote_exists_nonempty_true_and_false(monkeypatch):
    set_config(Config(remote_host="prod-01"))

    async def fake_ok(_cmdline: str, **_kwargs):
        return ""

    monkeypatch.setattr(fsops, "run_remote_shell", fake_ok)
    try:
        assert await fsops.exists_nonempty("/tmp/a") is True
    finally:
        set_config(Config())

    set_config(Config(remote_host="prod-01"))

    async def fake_fail(_cmdline: str, **_kwargs):
        raise TmuxError(["ssh"], 1, "not found")

    monkeypatch.setattr(fsops, "run_remote_shell", fake_fail)
    try:
        assert await fsops.exists_nonempty("/tmp/a") is False
    finally:
        set_config(Config())


@pytest.mark.asyncio
async def test_remote_remove_tree_quoting(monkeypatch):
    set_config(Config(remote_host="prod-01"))
    recorded: list[str] = []

    async def fake(cmdline: str, **_kwargs):
        recorded.append(cmdline)
        return ""

    monkeypatch.setattr(fsops, "run_remote_shell", fake)
    try:
        await fsops.remove_tree("/tmp/a b")
        assert len(recorded) == 1
        assert "rm -rf '/tmp/a b'" in recorded[0]
    finally:
        set_config(Config())
