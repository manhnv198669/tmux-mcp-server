"""Tmux pane layout, sizing, and arrangement tools."""

import json
from typing import Literal

from tmux_mcp.core.formats import get_pane_format, make_sentinel, parse_line
from tmux_mcp.core.models import PaneModel
from tmux_mcp.core.runner import run_tmux

DirectionType = Literal["horizontal", "vertical"]
LayoutType = Literal[
    "even-horizontal",
    "even-vertical",
    "main-horizontal",
    "main-vertical",
    "tiled",
]


async def tmux_split_pane(
    target: str = "",
    direction: DirectionType = "vertical",
    size: int = 50,
    start_directory: str = "",
) -> str:
    """Split target pane horizontally or vertically.

    Single-invocation execution returning new PaneModel immediately.

    Args:
        target: Target pane ID (e.g. "%0").
        direction: Split direction ("horizontal" side-by-side or "vertical" top/bottom).
        size: Size percentage for new pane (default 50).
        start_directory: Working directory path for new pane.

    Returns:
        JSON string of created PaneModel.
    """
    sep = make_sentinel()
    args = ["split-window", "-P", "-F", get_pane_format(sep)]

    if direction == "horizontal":
        args.append("-h")
    else:
        args.append("-v")

    if size > 0 and size != 50:
        args.extend(["-l", f"{size}%"])
    if target:
        args.extend(["-t", target])
    if start_directory:
        args.extend(["-c", start_directory])

    raw = await run_tmux(args)
    fields = parse_line(raw.strip(), sep, expected_fields=13)
    if len(fields) >= 13:
        pane = PaneModel(
            id=fields[0],
            index=int(fields[1]) if fields[1].isdigit() else 0,
            active=fields[2] == "1",
            width=int(fields[3]) if fields[3].isdigit() else 0,
            height=int(fields[4]) if fields[4].isdigit() else 0,
            current_command=fields[5],
            current_path=fields[6],
            pid=int(fields[7]) if fields[7].isdigit() else 0,
            history_size=int(fields[8]) if fields[8].isdigit() else 0,
            dead=fields[9] == "1",
            zoomed=fields[10] == "1",
            window_id=fields[11],
            session_id=fields[12],
        )
        return json.dumps(pane.model_dump(), indent=2)

    return json.dumps({"status": "split", "target": target})


async def tmux_select_pane(
    target: str = "",
    direction: str = "",
) -> str:
    """Select active pane by ID or directional arrow (L, R, U, D).

    Args:
        target: Target pane ID (e.g. "%1").
        direction: Optional direction: "L" (left), "R" (right), "U" (up), "D" (down).

    Returns:
        JSON status message.
    """
    args = ["select-pane"]
    if direction:
        dir_flag = f"-{direction.upper()[0]}"
        if dir_flag in ("-L", "-R", "-U", "-D"):
            args.append(dir_flag)
    if target:
        args.extend(["-t", target])

    await run_tmux(args)
    return json.dumps({"status": "selected", "target": target, "direction": direction})


async def tmux_resize_pane(
    target: str = "",
    direction: str = "",
    adjustment: int = 5,
    width: int = 0,
    height: int = 0,
) -> str:
    """Resize a pane relative (L/R/U/D + amount) or to absolute width/height.

    Args:
        target: Target pane ID (e.g. "%0").
        direction: Direction to adjust: "L", "R", "U", "D".
        adjustment: Number of cells to adjust in specified direction (default 5).
        width: Absolute target width in columns.
        height: Absolute target height in lines.

    Returns:
        JSON status message.
    """
    args = ["resize-pane"]
    if target:
        args.extend(["-t", target])

    if width > 0:
        args.extend(["-x", str(width)])
    if height > 0:
        args.extend(["-y", str(height)])

    if not width and not height and direction:
        dir_flag = f"-{direction.upper()[0]}"
        if dir_flag in ("-L", "-R", "-U", "-D"):
            args.extend([dir_flag, str(adjustment)])

    await run_tmux(args)
    return json.dumps({"status": "resized", "target": target})


async def tmux_zoom_pane(target: str = "") -> str:
    """Toggle zoom state (maximize / restore) for target pane.

    Args:
        target: Target pane ID (e.g. "%0").

    Returns:
        JSON status message.
    """
    args = ["resize-pane", "-Z"]
    if target:
        args.extend(["-t", target])

    await run_tmux(args)
    return json.dumps({"status": "zoomed_toggled", "target": target})


async def tmux_swap_panes(
    target: str = "",
    to_pane: str = "",
) -> str:
    """Swap positions of two panes.

    Args:
        target: Pane to swap, e.g. "%0". Same role as `target` in move_pane.
        to_pane: Pane to swap it with, e.g. "%1".

    Returns:
        JSON status message.
    """
    args = ["swap-pane"]
    if target:
        args.extend(["-s", target])
    if to_pane:
        args.extend(["-t", to_pane])

    await run_tmux(args)
    return json.dumps({"status": "swapped", "target": target, "to_pane": to_pane})


async def tmux_move_pane(
    target: str = "",
    to_pane: str = "",
    direction: DirectionType = "vertical",
) -> str:
    """Move/join a pane into another window or pane layout.

    Args:
        target: Source pane ID (e.g. "%1").
        to_pane: Destination pane or window ID (e.g. "%0" or "@0").
        direction: Join direction ("horizontal" or "vertical").

    Returns:
        JSON status message.
    """
    args = ["join-pane"]
    if direction == "horizontal":
        args.append("-h")
    else:
        args.append("-v")

    if target:
        args.extend(["-s", target])
    if to_pane:
        args.extend(["-t", to_pane])

    await run_tmux(args)
    return json.dumps({"status": "moved", "target": target, "to_pane": to_pane})


async def tmux_break_pane(target: str = "", select: bool = False) -> str:
    """Break a pane out of its window into a new window.

    Args:
        target: Target pane ID to break out (e.g. "%1").
        select: If True, select newly created window (default False).

    Returns:
        JSON status response.
    """
    args = ["break-pane"]
    if not select:
        args.append("-d")
    if target:
        args.extend(["-s", target])

    await run_tmux(args)
    return json.dumps({"status": "broken", "target": target})


async def tmux_set_layout(
    target: str = "",
    layout: LayoutType = "tiled",
) -> str:
    """Set pane layout preset for a window.

    Args:
        target: Target window or pane ID.
        layout: Preset name: even-horizontal, even-vertical, main-horizontal, main-vertical, tiled.

    Returns:
        JSON status message.
    """
    args = ["select-layout"]
    if target:
        args.extend(["-t", target])
    args.append(layout)

    await run_tmux(args)
    return json.dumps({"status": "layout_set", "target": target, "layout": layout})


async def tmux_kill_pane(target: str = "") -> str:
    """Kill a specified tmux pane (destructive action).

    Args:
        target: Target pane ID (e.g. "%1").

    Returns:
        JSON status message.
    """
    if not target:
        return json.dumps({"error": "target pane ID required"})

    await run_tmux(["kill-pane", "-t", target])
    return json.dumps({"status": "killed", "target": target})
