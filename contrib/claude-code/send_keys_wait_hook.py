#!/usr/bin/env python3
"""Claude Code hook: wait for a command typed with tmux send_keys, then wake Claude.

`send_keys` only queues keystrokes, so the tool returns before the command it
submitted has printed anything, and every caller has to remember a follow-up
wait. This hook takes that off the model: Claude Code runs it in the background
(`asyncRewake`) after each `mcp__tmux__send_keys`, it watches the pane until the
command is done, and exits 2 -- which wakes Claude, even from idle, with the
pane's output as a system reminder. Claude is never blocked in the meantime.

CLAUDE CODE ONLY. This is a Claude Code hook, not part of the MCP server: it
works because Claude Code runs it around the tool call. Other agents that use
this MCP server (opencode, codex, Cursor, ...) do not read Claude Code hooks,
so for them nothing changes -- they still have to call `wait_command` (after
`run_command`) or read the pane themselves after `send_keys`.

Two entry points, wired up in settings.json:

    pre   PreToolUse,  synchronous, fast. Records what the pane was running
          BEFORE the keys went in. Afterwards the command is already running,
          and "is this pane a shell waiting to get its prompt back, or a REPL
          that never will" can no longer be told apart.
    post  PostToolUse, asyncRewake. Waits, then reports.

"Done" means:
  - pane was at a shell: the shell is the foreground process again and the
    screen has held still for a moment ("idle" -- provably finished);
  - pane was in a REPL/TUI: the screen has held still ("quiet" -- the best
    available signal where there is no prompt to return to);
  - neither, but nothing has changed on screen for a long while: reported as
    "stalled", because a command sitting silent is often waiting for input
    (a password, a y/N) and that is worth waking up for too.

Environment knobs (all optional):
  TMUX_MCP_HOOK_MAX_WAIT       seconds before giving up (default 1740; keep it
                               under the hook's `timeout`, or Claude Code kills
                               the hook and the report is lost)
  TMUX_MCP_HOOK_STALL_AFTER    seconds of unchanged screen that count as
                               "stalled" (default 60)
  TMUX_MCP_HOOK_SOCKET         tmux -L socket name, if the MCP server uses one
  TMUX_MCP_HOOK_OUTPUT_LINES   lines of pane output to report (default 40)
"""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

SHELLS = {"zsh", "bash", "fish", "sh", "dash", "ksh", "ash", "-zsh", "-bash", "-sh"}

POLL = 1.0
# How long the screen must hold still before a finished command counts as done.
QUIET = 1.2
MAX_WAIT = float(os.environ.get("TMUX_MCP_HOOK_MAX_WAIT", "1740"))
STALL_AFTER = float(os.environ.get("TMUX_MCP_HOOK_STALL_AFTER", "60"))
OUTPUT_LINES = int(os.environ.get("TMUX_MCP_HOOK_OUTPUT_LINES", "40"))
MAX_OUTPUT_CHARS = 6000

STATE_DIR = os.path.join(tempfile.gettempdir(), "tmux-mcp-send-keys-hook")


def tmux(host: str, *args: str, timeout: float = 10) -> str:
    base = ["tmux"]
    socket = os.environ.get("TMUX_MCP_HOOK_SOCKET", "")
    if socket:
        base += ["-L", socket]
    argv = [*base, *args]
    if host:
        # Same transport the MCP server uses for host=..., so a pane on another
        # machine is watched where it actually lives.
        argv = ["ssh", "-o", "BatchMode=yes", host, shlex.join(argv)]
    out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"tmux exited {out.returncode}")
    return out.stdout


def probe(host: str, target: str) -> tuple[str, str]:
    """Return (pane_id, foreground command) for a target."""
    args = ["display-message", "-p"]
    if target:
        args += ["-t", target]
    args.append("#{pane_id}\t#{pane_current_command}")
    pane_id, _, cmd = tmux(host, *args).strip().partition("\t")
    return pane_id, cmd.strip().lower()


def screen(host: str, pane_id: str) -> str:
    return tmux(host, "capture-pane", "-p", "-t", pane_id)


def state_path(name: str) -> str:
    return os.path.join(STATE_DIR, name.replace("/", "_").replace("%", "pane"))


def read_input() -> dict:
    try:
        return json.load(sys.stdin)
    except ValueError:
        return {}


def run_pre(data: dict) -> None:
    ti = data.get("tool_input") or {}
    if not ti.get("enter"):
        return
    host = ti.get("host") or ""
    pane_id, cmd = probe(host, ti.get("target") or "")
    os.makedirs(STATE_DIR, exist_ok=True)
    call_id = data.get("tool_use_id") or ""
    with open(state_path(call_id + ".json"), "w") as f:
        json.dump({"pane_id": pane_id, "started_in_shell": cmd in SHELLS, "command": cmd}, f)
    # Newest send_keys on a pane wins: an older watcher on the same pane would only
    # report a screen that a later command has already moved past.
    with open(state_path(f"{host}-{pane_id}.latest"), "w") as f:
        f.write(call_id)


def superseded(host: str, pane_id: str, call_id: str) -> bool:
    try:
        with open(state_path(f"{host}-{pane_id}.latest")) as f:
            return f.read().strip() != call_id
    except OSError:
        return False


def tail(host: str, pane_id: str) -> str:
    text = tmux(host, "capture-pane", "-p", "-J", "-t", pane_id, "-S", f"-{OUTPUT_LINES + 60}")
    lines = text.rstrip("\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    out = "\n".join(lines[-OUTPUT_LINES:])
    return out[-MAX_OUTPUT_CHARS:]


def run_post(data: dict) -> int:
    ti = data.get("tool_input") or {}
    if not ti.get("enter"):
        return 0
    # A refused send (copy-mode, protected target, bad pane) typed nothing. The
    # reply may arrive as a raw string or wrapped in MCP content blocks, with its
    # quotes escaped once or twice, so match loosely.
    if not re.search(r'status\W+sent\b', json.dumps(data.get("tool_response", ""))):
        return 0

    host = ti.get("host") or ""
    call_id = data.get("tool_use_id") or ""
    keys = ti.get("keys") or ""

    try:
        with open(state_path(call_id + ".json")) as f:
            st = json.load(f)
        os.unlink(state_path(call_id + ".json"))
    except (OSError, ValueError):
        # PreToolUse didn't record anything; the best guess left is the pane's
        # current state, which reads a still-running command as "not a shell".
        pane_id, cmd = probe(host, ti.get("target") or "")
        st = {"pane_id": pane_id, "started_in_shell": cmd in SHELLS}

    pane_id = st["pane_id"]
    saw_shell = bool(st.get("started_in_shell"))
    started = time.monotonic()
    last_screen = None
    changed_at = started
    cmd = ""
    status = "timeout"

    while True:
        time.sleep(POLL)
        if superseded(host, pane_id, call_id):
            return 0
        try:
            _, cmd = probe(host, pane_id)
            cur = screen(host, pane_id)
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            print(f"[tmux send_keys hook] pane {pane_id} can no longer be read: {e}", file=sys.stderr)
            return 2

        now = time.monotonic()
        if cur != last_screen:
            last_screen, changed_at = cur, now
        still = now - changed_at

        at_shell = cmd in SHELLS
        # Prompt hooks (starship, direnv, nvm) briefly own the foreground right as a
        # command ends, so shell-ness is "ever seen", not one sample.
        saw_shell = saw_shell or at_shell

        if saw_shell and at_shell and still >= QUIET:
            status = "idle"
            break
        if not saw_shell and still >= QUIET * 2:
            status = "quiet"
            break
        if still >= STALL_AFTER:
            status = "stalled"
            break
        if now - started >= MAX_WAIT:
            status = "timeout"
            break

    waited = round(time.monotonic() - started)
    meaning = {
        "idle": "finished (pane is back at its shell prompt)",
        "quiet": f"screen settled; pane is running '{cmd}', which has no shell prompt to return to",
        "stalled": f"still running '{cmd}', but nothing has changed on screen for {int(STALL_AFTER)}s "
        "-- it may be waiting for input",
        "timeout": f"still running '{cmd}'; this hook has stopped watching",
    }[status]
    shown = keys if len(keys) <= 120 else keys[:117] + "..."
    try:
        out = tail(host, pane_id)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        out = f"(could not capture pane: {e})"
    where = f"{pane_id} on {host}" if host else pane_id
    print(
        f"[tmux send_keys hook] `{shown}` in pane {where}, watched {waited}s: {meaning}.\n"
        f"Last lines of the pane:\n{out}",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    data = read_input()
    try:
        if mode == "pre":
            run_pre(data)
            return 0
        if mode == "post":
            return run_post(data)
    except Exception as e:  # a hook must never break the tool call
        if mode == "post":
            print(f"[tmux send_keys hook] watcher failed: {e}", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
