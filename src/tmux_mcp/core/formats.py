"""Dynamic delimiter and format strings for parsing tmux output safely.

Uses unique random UUID sentinels for each query, completely eliminating collision risk
with colons, unicode, or octal escape sequences (like \037).
"""

import uuid


def make_sentinel() -> str:
    """Generate a unique random sentinel for format parsing."""
    return f"__TMUX_MCP_F{uuid.uuid4().hex}__"


def unescape_tmux_value(val: str) -> str:
    """Unescape doubled backslashes returned by tmux -F format rendering."""
    if not val:
        return val
    return val.replace("\\\\", "\\")


def get_session_format(sep: str) -> str:
    return sep.join(
        [
            "#{session_id}",
            "#{session_name}",
            "#{session_attached}",
            "#{session_windows}",
            "#{session_created}",
            "#{session_width}",
            "#{session_height}",
        ]
    )


def get_window_format(sep: str) -> str:
    return sep.join(
        [
            "#{window_id}",
            "#{window_index}",
            "#{window_name}",
            "#{window_active}",
            "#{window_panes}",
            "#{session_id}",
        ]
    )


def get_pane_format(sep: str) -> str:
    return sep.join(
        [
            "#{pane_id}",
            "#{pane_index}",
            "#{pane_active}",
            "#{pane_width}",
            "#{pane_height}",
            "#{pane_current_command}",
            "#{pane_current_path}",
            "#{pane_pid}",
            "#{history_size}",
            "#{pane_dead}",
            "#{pane_in_mode}",
            "#{window_id}",
            "#{session_id}",
        ]
    )


def parse_line(line: str, sep: str, expected_fields: int = -1) -> list[str]:
    """Parse a single tmux output line split by dynamic sentinel sep."""
    line = line.strip("\r\n")
    if not line:
        return []
    if expected_fields > 0:
        return line.split(sep, maxsplit=expected_fields - 1)
    return line.split(sep)
