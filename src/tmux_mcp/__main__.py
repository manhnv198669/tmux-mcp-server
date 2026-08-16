"""Main entrypoint for tmux-mcp server.

Logging MUST be configured to sys.stderr at top before anything else,
to prevent corrupting the MCP stdio stdout transport.
"""

import argparse
import asyncio
import logging
import os
import sys

# Configure stderr logging immediately before importing anything else that might log
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("tmux_mcp")

from tmux_mcp.config import DEFAULT_COMMANDS_HISTORY_FILE, Config
from tmux_mcp.core.guard import parse_patterns
from tmux_mcp.server import create_server


def parse_args() -> Config:
    parser = argparse.ArgumentParser(
        description="tmux-mcp: Model Context Protocol server for tmux."
    )
    parser.add_argument(
        "--socket-name",
        "-L",
        default="",
        help="tmux socket name (equivalent to tmux -L)",
    )
    parser.add_argument(
        "--socket-path",
        "-S",
        default="",
        help="tmux socket path (equivalent to tmux -S)",
    )
    parser.add_argument(
        "--shell-type",
        choices=["bash", "zsh", "fish"],
        default="zsh",
        help="Default shell type for command epilogues (default: zsh)",
    )
    parser.add_argument(
        "--tools",
        default="standard",
        help="Tool profile: read, standard, full, or comma-separated list of tool names",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Enforce read-only mode, disabling all mutating tools",
    )
    parser.add_argument(
        "--protect",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Refuse every mutating tool on targets matching PATTERN, while keeping them "
            "readable. Repeatable, and comma-separated values are accepted. Matches a "
            "session name, session:window, session:window.pane, or a %%pane/@window/$session "
            "id, with shell globs: --protect 'prod-*' --protect 'skinstrading:3*'. "
            "Also settable via TMUX_MCP_PROTECTED_TARGETS."
        ),
    )
    parser.add_argument(
        "--default-capture-lines",
        type=int,
        default=200,
        help="Default lines to capture in read_pane (default: 200)",
    )
    parser.add_argument(
        "--commands-history-file",
        default=DEFAULT_COMMANDS_HISTORY_FILE,
        metavar="PATH",
        help=(
            "Append every executed command to this text file, with timestamp, pane, "
            "working directory, exit code and duration. Created if missing. "
            f"(default: {DEFAULT_COMMANDS_HISTORY_FILE})"
        ),
    )
    parser.add_argument(
        "--no-save-commands-history",
        action="store_true",
        help="Record executed commands nowhere. Overrides --commands-history-file.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    numeric_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.getLogger().setLevel(numeric_level)

    protected = parse_patterns(
        [*args.protect, os.environ.get("TMUX_MCP_PROTECTED_TARGETS", "")]
    )

    return Config(
        protected_targets=protected,
        socket_name=args.socket_name,
        socket_path=args.socket_path,
        shell_type=args.shell_type,
        tool_profile=args.tools,
        read_only=args.read_only,
        default_capture_lines=args.default_capture_lines,
        log_level=args.log_level,
        save_commands_history=not args.no_save_commands_history,
        commands_history_file=args.commands_history_file,
    )


def main() -> None:
    config = parse_args()
    logger.info(
        "Starting tmux-mcp server (profile: %s, read_only: %s, protected: %s, history: %s)",
        config.tool_profile,
        config.read_only,
        ", ".join(config.protected_targets) or "none",
        config.commands_history_file if config.save_commands_history else "disabled",
    )
    app = create_server(config)
    asyncio.run(app.run_stdio_async())


if __name__ == "__main__":
    main()
