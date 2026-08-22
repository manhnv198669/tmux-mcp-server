"""Shell epilogue templates with execution boundary markers for clean output extraction."""

import shutil

from tmux_mcp.core.runner import get_socket_args


def build_epilogue(
    command: str,
    rc_file: str,
    channel: str,
    cmd_id: str,
    shell_type: str = "zsh",
    remote: bool = False,
) -> str:
    """Build a compound command string appending start/end markers, exit code capture, and wait-for signal.

    When remote is True the tmux binary is referenced as plain "tmux": a locally
    resolved path (shutil.which) does not exist on the remote host.
    """
    sock_flags = get_socket_args()
    sock_str = " ".join(sock_flags)
    tmux_bin = "tmux" if remote else (shutil.which("tmux") or "tmux")
    tmux_cmd = f"'{tmux_bin}' {sock_str}".strip()

    start_marker = f"__TMUX_MCP_START_{cmd_id}__"
    end_marker = f"__TMUX_MCP_END_{cmd_id}__"

    if shell_type.lower() == "fish":
        epilogue = (
            f"printf '%s\\n' '{start_marker}'; {command}; set __rc $status; "
            f"printf '\\n%s\\n' '{end_marker}'; printf '%s' \"$__rc\" > '{rc_file}'; "
            f"{tmux_cmd} wait-for -S '{channel}'"
        )
    else:  # zsh, bash, sh
        epilogue = (
            f"printf '%s\\n' '{start_marker}'; {command}; __rc=$?; "
            f"printf '\\n%s\\n' '{end_marker}'; printf '%s' \"$__rc\" > '{rc_file}'; "
            f"{tmux_cmd} wait-for -S '{channel}'"
        )

    # Ensure no raw literal \n characters exist in epilogue string (so send-keys doesn't trigger prematurely)
    return epilogue.replace("\r", "").replace("\n", " ")
