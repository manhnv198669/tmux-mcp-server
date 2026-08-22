"""Configuration settings for tmux-mcp."""

from dataclasses import dataclass, field

# Defaulting under /tmp is deliberate: the OS reclaims it on its own schedule, so an
# audit log nobody reads cannot grow forever. Point --commands-history-file
# elsewhere to keep it.
DEFAULT_COMMANDS_HISTORY_FILE = "/tmp/.tmux-mcp-server-history"


@dataclass
class Config:
    socket_name: str = ""
    socket_path: str = ""
    shell_type: str = "zsh"  # bash, zsh, fish
    tool_profile: str = "standard"  # read, standard, full, or comma-separated names
    read_only: bool = False
    # fnmatch patterns; any target resolving to a match rejects every mutating tool.
    protected_targets: tuple[str, ...] = ()
    default_capture_lines: int = 200
    log_level: str = "INFO"
    # Commands run through run_command are recorded here rather than in the user's
    # shell history, which is theirs to navigate.
    save_commands_history: bool = True
    commands_history_file: str = DEFAULT_COMMANDS_HISTORY_FILE
    remote_host: str = ""
    remote_ssh_opts: tuple[str, ...] = ()
    remote_ssh_overhead: float = 5.0
    remote_tmp_dir: str = "/tmp"
    allowed_hosts: tuple[str, ...] = ()
    host_sockets: dict[str, str] = field(default_factory=dict)


_global_config: Config = Config()


def get_config() -> Config:
    return _global_config


def set_config(config: Config) -> None:
    global _global_config
    _global_config = config
