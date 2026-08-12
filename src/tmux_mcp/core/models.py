"""Pydantic data models for tmux entities."""

from pydantic import BaseModel, Field


class SessionModel(BaseModel):
    id: str = Field(description="Session ID, e.g. $0")
    name: str = Field(description="Session name")
    attached: bool = Field(description="Whether a client is currently attached")
    windows_count: int = Field(description="Number of windows in session")
    created_ts: int = Field(description="Creation unix timestamp")
    width: int = Field(default=0, description="Session width in characters")
    height: int = Field(default=0, description="Session height in lines")


class WindowModel(BaseModel):
    id: str = Field(description="Window ID, e.g. @0")
    index: int = Field(description="Window index within session")
    name: str = Field(description="Window name")
    active: bool = Field(description="Whether window is active in session")
    panes_count: int = Field(description="Number of panes in window")
    session_id: str = Field(description="Belonging session ID")


class PaneModel(BaseModel):
    id: str = Field(description="Pane ID, e.g. %0")
    index: int = Field(description="Pane index within window")
    active: bool = Field(description="Whether pane is active in window")
    width: int = Field(description="Pane width in characters")
    height: int = Field(description="Pane height in lines")
    current_command: str = Field(description="Currently running foreground command")
    current_path: str = Field(description="Current working directory")
    pid: int = Field(description="PID of shell or process in pane")
    history_size: int = Field(description="Number of lines in scrollback history")
    dead: bool = Field(description="Whether pane process has exited")
    zoomed: bool = Field(default=False, description="Whether pane is zoomed")
    window_id: str = Field(description="Belonging window ID")
    session_id: str = Field(description="Belonging session ID")


class CommandRunModel(BaseModel):
    command_id: str = Field(description="Unique ID of executed command")
    pane_id: str = Field(description="Target pane ID")
    command: str = Field(description="Executed command string")
    status: str = Field(description="Status: running, completed, failed, timeout, cancelled")
    exit_code: int = Field(default=-1, description="Exit code (-1 if still running or unknown)")
    output: str = Field(default="", description="Captured stdout/stderr text")
    truncated: bool = Field(default=False, description="Whether output was truncated")
    created_at: float = Field(description="Timestamp when command started")
