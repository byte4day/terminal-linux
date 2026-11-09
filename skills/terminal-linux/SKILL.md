---
name: terminal-linux
description: Drive a separate Xvfb Linux desktop (screenshot, click, type, windows, clipboard, wait_stable, run_in_terminal) without touching the host desktop. Use for computer-use tasks that need an isolated guest UI.
---

# terminal-linux

Private Linux desktop for computer-use ([Agent Skills](https://agentskills.io/) package). Guest has **agent-terminal** and usually **Firefox**. Never control the host desktop. Prefer the host default / `inherit` model; Claude computer-use work usually fits **Opus** or **Fable** — do not hard-pin unless the user asks.

## Loop

1. `status` → if not running, `up`.
2. `screenshot` — coordinates are pixels in this image (top-left).
3. Prefer `windows` / `focus` / `run_in_terminal` / `key` / `open_url`.
4. Act with `click`, `type`, `key`, `scroll`, `drag`, or clipboard paste.
5. `wait_stable` or `screenshot` again.
6. `stop` when done.

## Install

```bash
/plugin marketplace add byte4day/terminal-linux
/plugin install terminal-linux@terminal-linux
# or
terminal-linux plugins install --all
claude mcp add terminal-linux -- terminal-linux mcp default
```

## Safety

- Guest shares host user/files/network by default.
- Never fall back to host screenshot/input tools.
