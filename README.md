# tmux-mcp

> Model Context Protocol (MCP) server for **tmux**, written in Python and distributed via `uvx`.

Exposes **37 granular tools** covering sessions, windows, panes, layouts, status inspection, and secure command execution using event-driven `pipe-pane` + `wait-for` primitives.

---

## Key Features & Security Design

- **No Shell Injection Vulnerabilities**: All tmux interactions execute strictly via argv parameter arrays without `shell=True`.
- **Event-Driven Execution Engine**: Uses `pipe-pane` streams and `tmux wait-for` events instead of polling or scrollback regex. Captures exact return codes and complete output streams (>50,000 lines tested without truncation).
- **Interactive App Guard**: Automatically blocks non-shell panes (e.g. `vim`, `htop`, `python`) from accidental command injection, prompting the caller to use keypress tools (`send_keys`) instead.
- **Strict Protocol & Output Purity**: Zero stray stdout prints to prevent corrupting the MCP stdio JSON-RPC transport stream (logging strictly routed to `sys.stderr`).
- **Portable Flat Tool Schemas**: Compatible with all MCP clients (Claude Code, Claude Desktop, OpenCode, Cursor, Windsurf, Zed, Continue, VS Code) by enforcing flat JSON schemas without unsupported `$ref`/`$defs`/`anyOf` constructs.

---

## Quick Start

Run instantly without installing Python dependencies using `uvx`:

```bash
# Run with standard profile (default 22 tools)
uvx tmux-mcp-server

# Run with full profile (all 37 tools including destructive actions)
uvx tmux-mcp-server --tools=full

# Run in read-only mode (13 read tools)
uvx tmux-mcp-server --read-only
```

---

## Tool Profiles

| Profile | Tools Count | Description |
|---|---|---|
| `standard` (default) | 22 | All read, interact, split, resize, layout, and command execution tools (excludes destructive `kill-*` tools). |
| `full` | 37 | Complete set of 37 tools, including destructive operations (`kill_session`, `kill_window`, `kill_pane`). |
| `read` | 13 | Read-only inspection tools. Safe for unrestricted agent usage. |
| Custom | N | Comma-separated list of tool names (e.g. `--tools=list_sessions,read_pane,run_command`). |

---

## Client Configuration Examples

> **Watch the package name.** This project is `tmux-mcp-server`. Do **not**
> configure `"args": ["tmux-mcp"]` — `tmux-mcp` is an unrelated, already-published
> PyPI package, and `uvx` would silently download and run that one instead.
>
> **Working on the code?** Point the client at your checkout so edits take effect
> immediately:
>
> ```json
> "args": ["run", "--directory", "/absolute/path/to/tmux-mcp-server", "tmux-mcp-server"]
> ```
>
> with `"command": "uv"`. Note that `uvx --from <path>` caches the built wheel per
> version, so local edits are **not** picked up until you bump `version` in
> `pyproject.toml` — `uv run --directory` has no such caching.

### 1. Claude Code
Add to `~/.claude.json` or `.claude.json`:

```json
{
  "mcpServers": {
    "tmux": {
      "command": "uvx",
      "args": ["tmux-mcp-server"]
    }
  }
}
```

### 2. Claude Desktop
Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "tmux": {
      "command": "uvx",
      "args": ["tmux-mcp-server"]
    }
  }
}
```

### 3. OpenCode
Add to `~/.config/opencode/opencode.json` (or project `.opencode/mcp.json`):

```json
{
  "mcpServers": {
    "tmux": {
      "command": "uvx",
      "args": ["tmux-mcp-server"]
    }
  }
}
```

### 4. Cursor
Add to **Settings** -> **Features** -> **MCP**:
- Name: `tmux`
- Type: `command`
- Command: `uvx tmux-mcp-server`

### 5. Windsurf
Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "tmux": {
      "command": "uvx",
      "args": ["tmux-mcp-server"]
    }
  }
}
```

### 6. Zed
Add to `~/.config/zed/settings.json`:

```json
{
  "context_servers": {
    "tmux": {
      "command": {
        "path": "uvx",
        "args": ["tmux-mcp-server"]
      }
    }
  }
}
```

### 7. Continue
Add to `~/.continue/config.json`:

```json
{
  "mcpServers": [
    {
      "name": "tmux",
      "command": "uvx",
      "args": ["tmux-mcp-server"]
    }
  ]
}
```

### 8. VS Code (Roo Code / Cline)
Add to `.vscode/mcp.json`:

```json
{
  "mcpServers": {
    "tmux": {
      "command": "uvx",
      "args": ["tmux-mcp-server"]
    }
  }
}
```

### 9. Generic Stdio Client
Any MCP-compliant client can launch via stdio:

```json
{
  "command": "uvx",
  "args": ["tmux-mcp-server"]
}
```

---

## Tool Reference (37 Tools)

### Sessions (6)
- `list_sessions`
- `get_session`
- `create_session`
- `rename_session`
- `switch_client`
- `kill_session` ⚠️

### Windows (6)
- `list_windows`
- `create_window`
- `rename_window`
- `select_window`
- `move_window`
- `kill_window` ⚠️

### Panes — Read & Interact (7)
- `list_panes`
- `get_pane_info`
- `read_pane`
- `search_pane`
- `send_keys`
- `send_special_key`
- `clear_pane`

### Panes — Layout & Sizing (9)
- `split_pane`
- `select_pane`
- `resize_pane`
- `zoom_pane`
- `swap_panes`
- `move_pane`
- `break_pane`
- `set_layout`
- `kill_pane` ⚠️

### Command Execution (5)
- `run_command`
- `get_command_result`
- `wait_command`
- `list_commands`
- `cancel_command`

### Server & Inspection (4)
- `server_info`
- `list_clients`
- `display_message`
- `show_options`

---

## Development & Testing

Run all unit and integration tests (using an isolated test socket `-L tmux-mcp-test`):

```bash
uv run pytest
```

---

## License

MIT
