"""Tests for prefix key resolution and key validation."""

from unittest.mock import AsyncMock, patch

import pytest

from tmux_mcp.core.prefix import resolve_prefix
from tmux_mcp.tools.panes import tmux_send_special_key, validate_key


class TestValidateKey:
    """Tests for validate_key function."""

    def test_accepts_ct(self):
        assert validate_key("C-t") == "C-t"

    def test_accepts_cb(self):
        assert validate_key("C-b") == "C-b"

    def test_accepts_mx(self):
        assert validate_key("M-x") == "M-x"

    def test_accepts_cm_left(self):
        assert validate_key("C-M-Left") == "C-M-Left"

    def test_accepts_f12(self):
        assert validate_key("F12") == "F12"

    def test_rejects_f13_which_tmux_does_not_know(self):
        # tmux would type the literal string "F13" into the pane instead of sending a key.
        with pytest.raises(ValueError, match="unknown key name"):
            validate_key("F13")

    def test_accepts_enter(self):
        assert validate_key("Enter") == "Enter"

    def test_accepts_q(self):
        assert validate_key("q") == "q"

    def test_accepts_s_tab(self):
        assert validate_key("S-Tab") == "S-Tab"

    def test_accepts_space(self):
        assert validate_key("Space") == "Space"

    def test_accepts_case_insensitive(self):
        assert validate_key("c-t") == "c-t"
        assert validate_key("enter") == "enter"
        assert validate_key("C-m-Left") == "C-m-Left"

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="empty or whitespace"):
            validate_key("")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValueError, match="empty or whitespace"):
            validate_key("   ")

    def test_rejects_rm_rf(self):
        with pytest.raises(ValueError, match="spaces"):
            validate_key("rm -rf /")

    def test_rejects_a_b(self):
        with pytest.raises(ValueError, match="spaces"):
            validate_key("a b")

    def test_rejects_c_only(self):
        with pytest.raises(ValueError, match="unknown key name"):
            validate_key("C-")

    def test_rejects_40_char_string(self):
        long_key = "C-" + "a" * 38
        with pytest.raises(ValueError, match="too long"):
            validate_key(long_key)

    def test_rejects_duplicate_modifier(self):
        with pytest.raises(ValueError, match="duplicate modifier"):
            validate_key("C-C-t")

    def test_rejects_invalid_modifier(self):
        with pytest.raises(ValueError, match="invalid modifier"):
            validate_key("X-t")

    def test_rejects_control_char(self):
        with pytest.raises(ValueError, match="invalid printable character"):
            validate_key("\x01")


class TestResolvePrefix:
    """Tests for resolve_prefix function."""

    @pytest.mark.asyncio
    async def test_returns_ct_when_run_tmux_returns_ct(self):
        with patch("tmux_mcp.core.prefix.run_tmux", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "C-t\n"
            result = await resolve_prefix()
            assert result == "C-t"

    @pytest.mark.asyncio
    async def test_raises_when_returns_none(self):
        with patch("tmux_mcp.core.prefix.run_tmux", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "none\n"
            with pytest.raises(ValueError, match="no prefix key configured"):
                await resolve_prefix()

    @pytest.mark.asyncio
    async def test_raises_when_returns_empty(self):
        with patch("tmux_mcp.core.prefix.run_tmux", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "\n"
            with pytest.raises(ValueError, match="no prefix key configured"):
                await resolve_prefix()


class TestSendSpecialKeyPrefix:
    """Tests for tmux_send_special_key with Prefix pseudo-key."""

    @pytest.mark.asyncio
    async def test_prefix_resolves_and_sends_resolved_key(self):
        with (
            patch("tmux_mcp.tools.panes.run_tmux", new_callable=AsyncMock) as mock_run_tmux,
            patch("tmux_mcp.tools.panes.resolve_prefix", new_callable=AsyncMock) as mock_resolve,
        ):
            mock_resolve.return_value = "C-t"
            await tmux_send_special_key(key="Prefix")

            mock_resolve.assert_called_once()
            args, _kwargs = mock_run_tmux.call_args
            assert "C-t" in args[0]

    @pytest.mark.asyncio
    async def test_prefix_override_sends_override_and_not_call_resolve(self):
        with (
            patch("tmux_mcp.tools.panes.run_tmux", new_callable=AsyncMock) as mock_run_tmux,
            patch("tmux_mcp.tools.panes.resolve_prefix", new_callable=AsyncMock) as mock_resolve,
        ):
            await tmux_send_special_key(key="Prefix", prefix_override="C-b")

            mock_resolve.assert_not_called()
            args, _kwargs = mock_run_tmux.call_args
            assert "C-b" in args[0]

    @pytest.mark.asyncio
    async def test_prefix_validates_override(self):
        with (
            patch("tmux_mcp.tools.panes.run_tmux", new_callable=AsyncMock),
            pytest.raises(ValueError, match="unknown key name"),
        ):
            await tmux_send_special_key(key="Prefix", prefix_override="C-")

    @pytest.mark.asyncio
    async def test_regular_key_still_works(self):
        with patch("tmux_mcp.tools.panes.run_tmux", new_callable=AsyncMock) as mock_run_tmux:
            await tmux_send_special_key(key="Enter")

            args, _kwargs = mock_run_tmux.call_args
            assert "Enter" in args[0]