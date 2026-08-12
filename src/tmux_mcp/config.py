"""Configuration settings for tmux-mcp."""

from dataclasses import dataclass
import os


@dataclass
class Config:
    socket_name: str = ""
    socket_path: str = ""
    shell_type: str = "zsh"  # bash, zsh, fish
    tool_profile: str = "standard"  # read, standard, full, or comma-separated names
    read_only: bool = False
    default_capture_lines: int = 200
    log_level: str = "INFO"


_global_config: Config = Config()


def get_config() -> Config:
    return _global_config


def set_config(config: Config) -> None:
    global _global_config
    _global_config = config
