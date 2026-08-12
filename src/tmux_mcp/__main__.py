"""Main entrypoint for tmux-mcp server.

Logging MUST be configured to sys.stderr at top before anything else,
to prevent corrupting the MCP stdio stdout transport.
"""

import argparse
import asyncio
import logging
import sys

# Configure stderr logging immediately before importing anything else that might log
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("tmux_mcp")

from tmux_mcp.config import Config
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
        "--default-capture-lines",
        type=int,
        default=200,
        help="Default lines to capture in read_pane (default: 200)",
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

    return Config(
        socket_name=args.socket_name,
        socket_path=args.socket_path,
        shell_type=args.shell_type,
        tool_profile=args.tools,
        read_only=args.read_only,
        default_capture_lines=args.default_capture_lines,
        log_level=args.log_level,
    )


def main() -> None:
    config = parse_args()
    logger.info("Starting tmux-mcp server (profile: %s, read_only: %s)", config.tool_profile, config.read_only)
    app = create_server(config)
    asyncio.run(app.run_stdio_async())


if __name__ == "__main__":
    main()
