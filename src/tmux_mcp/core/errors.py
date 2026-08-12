"""Custom exceptions for tmux-mcp operations."""


class TmuxError(Exception):
    """Base exception for tmux execution errors."""

    def __init__(self, argv: list[str], returncode: int, stderr: str):
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr.strip()
        cmd_str = " ".join(argv)
        super().__init__(f"tmux command failed [{returncode}]: {cmd_str}\n{self.stderr}")


class PaneBusyError(Exception):
    """Raised when trying to run a command in a pane running a non-shell process."""

    def __init__(self, pane_id: str, current_command: str):
        self.pane_id = pane_id
        self.current_command = current_command
        super().__init__(
            f"Pane '{pane_id}' is busy running '{current_command}'. "
            f"Use send_keys to interact with non-shell applications."
        )


class TmuxNotRunningError(Exception):
    """Raised when tmux server is not running or socket is unreachable."""

    def __init__(self, socket_info: str = ""):
        self.socket_info = socket_info
        msg = "tmux server is not running"
        if socket_info:
            msg += f" on socket {socket_info}"
        super().__init__(msg)


class CommandTimeoutError(Exception):
    """Raised when command execution exceeds timeout."""

    def __init__(self, command_id: str, timeout: float):
        self.command_id = command_id
        self.timeout = timeout
        super().__init__(f"Command '{command_id}' timed out after {timeout} seconds.")
