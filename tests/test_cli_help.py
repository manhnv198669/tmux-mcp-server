"""The CLI must be able to print its own help.

argparse runs every help string through `%` formatting, so a literal percent in
one -- `%pane` for a tmux pane id, say -- raises ValueError and takes `--help`
down with it. Nothing else in the suite touches that code path, and the failure
only shows up for a user typing --help, so it is asserted here.
"""

import pytest

from tmux_mcp.__main__ import parse_args


def test_help_renders(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["tmux-mcp-server", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        parse_args()
    assert excinfo.value.code == 0
    assert "--protect" in capsys.readouterr().out
