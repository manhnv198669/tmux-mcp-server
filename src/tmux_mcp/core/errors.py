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


class PaneInModeError(Exception):
    """Raised when writing to a pane whose copy/view mode would swallow the keys.

    While a pane sits in copy-mode, tmux routes every key into the mode's own key
    table instead of the pty. Keys are not merely dropped: leading characters are
    consumed as copy-mode commands, one of them cancels the mode, and the remaining
    characters fall through to the shell and run as a truncated command. Refusing
    loudly is the only safe option.
    """

    def __init__(self, pane_id: str, mode: str = "copy-mode"):
        self.pane_id = pane_id
        self.mode = mode
        shown = pane_id or "<current pane>"
        super().__init__(
            f"Pane '{shown}' is in {mode} (someone is viewing its scrollback). "
            f"Keys sent now would be partly eaten by the mode and partly executed as a "
            f"truncated command. Pass exit_copy_mode=true to leave the mode first "
            f"(this moves the viewer's screen back to the live output), or wait."
        )


class ProtectedTargetError(Exception):
    """Raised when a mutating tool is aimed at a target covered by --protect."""

    def __init__(self, target: str, identity: str, pattern: str):
        self.target = target
        self.identity = identity
        self.pattern = pattern
        shown = target or "<current pane>"
        super().__init__(
            f"Refusing to mutate '{shown}': it resolves to '{identity}', "
            f"which is protected by pattern '{pattern}'. "
            f"Read-only tools (read_pane, search_pane, get_pane_info) still work on it."
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
