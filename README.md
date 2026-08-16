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

# Keep production sessions readable but reject every write to them
uvx tmux-mcp-server --protect 'prod-*' --protect 'skinstrading:3*'
```

---

## Protecting Specific Targets

`--read-only` is all-or-nothing: it strips every mutating tool from the server. When
you want an agent that can freely drive scratch sessions but must never type into the
one attached to production, protect that target by name instead:

```bash
uvx tmux-mcp-server --protect 'prod-*,skinstrading:3*'
# or
TMUX_MCP_PROTECTED_TARGETS='prod-*,skinstrading:3*' uvx tmux-mcp-server
```

Protected targets stay fully readable (`read_pane`, `search_pane`, `get_pane_info`);
only mutating tools refuse them, and they refuse *before* tmux is invoked.

Matching is by identity, not by the string the caller happened to use. A target is
resolved through tmux first, then every name it answers to is tested against the
patterns as a shell glob:

| Form | Example |
|---|---|
| session | `skinstrading` |
| session:window index | `skinstrading:3` |
| session:window name | `skinstrading:skinner-server` |
| session:window.pane | `skinstrading:3.0` |
| raw ids | `%88`, `@51`, `$4` |

So `--protect 'skinstrading:3*'` also blocks a call that named the pane `%88`. An
omitted `target` is checked too, since it resolves to tmux's current pane.

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

`create_session` pins the size you ask for. tmux's default `window-size latest` would
otherwise resize a detached window to whatever client is newest on the server and
silently discard `-x/-y`. This matters when driving a TUI: the same screen captured at
320 columns costs roughly five times more to read back than at 120.

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

**Full-screen apps and nested tmux.** While a pane runs vim, htop, less, or a tmux
attached over ssh, the terminal is on its *alternate screen* and tmux keeps no
reachable scrollback for it — only the visible screen exists. Reading works normally
(a nested tmux is just rendered text, at any nesting depth), but history does not, so:

- `get_pane_info` reports `alternate_on`
- `read_pane` returns `scrollback_available: false`, a `warning`, and sets `truncated`
  when history was requested and could not be delivered
- `search_pane` reports `searched_lines` and warns that a zero result covers only the
  visible screen

`read_pane(join_wrapped=true)` rejoins lines the terminal split at pane width, so a
long value broken across two rows comes back as one string.

Note that `list_panes` never sees panes *inside* a nested tmux: that inner server has
its own socket, usually on another machine.

**Panes someone is viewing.** copy-mode belongs to the pane, not to a client —
`copy-mode` has no `-c` flag, and every client watching the pane sees the same mode.
A pane being scrolled and a pane being typed into are therefore mutually exclusive
states, and typing into a pane in copy-mode does not fail cleanly. tmux routes each
key into the mode's key table: leading characters are consumed as copy-mode commands,
one of them cancels the mode, and the tail falls through to the shell and runs. Sending
`echo MARKER` at a pane in copy-mode leaves `bash: RKER: command not found`.

`send_keys`, `send_special_key`, and `run_command` therefore refuse a pane in
copy-mode. Pass `exit_copy_mode=true` to cancel the mode first — which yanks a human
viewer's screen back to the live output, so it is opt-in rather than automatic.

To watch a pane's output while an agent keeps typing into it, do not scroll the pane
itself. Tee it and read the copy instead:

```bash
tmux pipe-pane -t <agent-pane> -o 'cat >> /tmp/agent.log'
less +F /tmp/agent.log   # your own pane, your own scrollback
```

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

**Command history.** `run_command` types into a real interactive shell, so every
command it runs also lands in that shell's history. That history belongs to the
human — it is what a prefix search walks through — and it cannot hold what an audit
actually needs anyway: no exit code, no timestamp, no pane, no duration. So the
server keeps its own log, tab-separated, one line per event:

```
ts                        event  command_id        pane  exit  elapsed  cwd     command
2026-08-17T00:49:30+0700  RUN    cmd_790182afe03d  %0    -     -        /repo   uv run pytest
2026-08-17T00:49:31+0700  OK     cmd_790182afe03d  %0    0     0.23s    /repo   uv run pytest
```

Dispatch is logged before the command finishes, so `tail -f` shows work in flight
rather than only what has already completed. Events are `RUN`, `OK`, `FAIL` and
`CANCEL`, which makes `grep FAIL` worth typing. `pane` is the resolved `%id`, not
the string the caller passed, since session names get reused.

```bash
# default: /tmp/.tmux-mcp-server-history, so the OS reclaims it on its own schedule
uvx tmux-mcp-server --commands-history-file ~/.tmux-mcp/commands.log
uvx tmux-mcp-server --no-save-commands-history      # record nothing; wins over the flag above
```

The file is created if missing, opened append-only and mode `0600`, and never
followed through a symlink — the default sits in a world-writable `/tmp`, and these
lines carry every command and working directory of the session. A write failure is
logged once and never propagates: the history must not be able to break the command
it is recording.

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

The suite runs under `asyncio_mode = "auto"`: every test here is a coroutine driving
tmux, so a missing `@pytest.mark.asyncio` can no longer make a test pass by never
being awaited.

Lint runs on commit. Install the hook once:

```bash
uv run pre-commit install
uv run ruff check .          # same check, on demand
```

The hook shells out to `uv run ruff`, so it uses exactly the ruff pinned in the dev
dependency group rather than a separate copy that could drift.

---

## License

MIT
