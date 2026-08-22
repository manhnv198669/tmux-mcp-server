"""Tests for per-call remote host context."""

import asyncio

import pytest

from tmux_mcp.config import Config, set_config
from tmux_mcp.core.context import current_host, use_host
from tmux_mcp.core.runner import build_argv


def test_current_host_returns_empty_by_default():
    set_config(Config())
    try:
        assert current_host() == ""
    finally:
        set_config(Config())


def test_current_host_returns_config_when_no_context():
    set_config(Config(remote_host="cfg-host"))
    try:
        assert current_host() == "cfg-host"
    finally:
        set_config(Config())


def test_use_host_overrides_and_unwinds():
    set_config(Config(remote_host="cfg-host"))
    try:
        with use_host("h1"):
            assert current_host() == "h1"
        assert current_host() == "cfg-host"
    finally:
        set_config(Config())


def test_use_host_unwinds_nested():
    set_config(Config())
    try:
        with use_host("h1"):
            assert current_host() == "h1"
            with use_host("h2"):
                assert current_host() == "h2"
            assert current_host() == "h1"
        assert current_host() == ""
    finally:
        set_config(Config())


def test_use_host_restores_on_exception():
    set_config(Config(remote_host="cfg-host"))
    try:
        with use_host("h1"):
            assert current_host() == "h1"
            raise ValueError("boom")
    except ValueError:
        pass
    assert current_host() == "cfg-host"


def test_build_argv_local_outside_block():
    set_config(Config())
    try:
        result = build_argv(["list-panes"], [])
        assert result == ["tmux", "list-panes"]
    finally:
        set_config(Config())


def test_build_argv_remote_inside_use_host():
    set_config(Config())
    try:
        with use_host("h1"):
            result = build_argv(["list-panes"], [])
            assert result[0] == "ssh"
            assert "h1" in result
            assert "list-panes" in result[-1]
    finally:
        set_config(Config())


@pytest.mark.asyncio
async def test_isolation_across_asyncio_tasks():
    set_config(Config())
    try:
        results = {}

        async def task_a():
            with use_host("h1"):
                results["a_before"] = current_host()
                await asyncio.sleep(0)
                results["a_after"] = current_host()

        async def task_b():
            with use_host("h2"):
                results["b_before"] = current_host()
                await asyncio.sleep(0)
                results["b_after"] = current_host()

        await asyncio.gather(task_a(), task_b())

        assert results["a_before"] == "h1"
        assert results["a_after"] == "h1"
        assert results["b_before"] == "h2"
        assert results["b_after"] == "h2"
    finally:
        set_config(Config())
