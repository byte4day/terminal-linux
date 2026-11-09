# terminal-linux

**A Linux desktop for AI agents — live in your terminal.**

`terminal-linux` boots a private desktop session, streams it into the terminal, and exposes MCP + CLI tools so agents can click, type, open apps, and run shell commands without touching your host pointer or screen.

Built by [byte4day](https://github.com/byte4day).

![Live desktop preview](assets/screenshot-desktop.png)

## Features

- Live terminal preview of the guest desktop (high-quality graphics terminals, ANSI fallback elsewhere)
- Own **agent-terminal** + **Firefox** workspace by default
- MCP tools for computer use: screenshot, click, type, windows, clipboard, wait, run_in_terminal, …
- Agent skill + Claude Code plugin marketplace
- One-terminal mode: keep `terminal-linux up` open; agents drive the same session over MCP

> Display isolation only (Xvfb). Same Linux user/filesystem/network as the host unless you add your own sandbox.

## Requirements

| Tool | Why |
|------|-----|
| Linux | host |
| `Xvfb` | virtual display |
| `xdotool` | input |
| ImageMagick | screenshots |
| `openbox` (or vendored copy) | window manager |
| `wmctrl`, `xclip` | window + clipboard helpers |
| Alacritty/Kitty + Firefox | recommended guest apps |

## Install

```bash
git clone https://github.com/byte4day/terminal-linux.git
cd terminal-linux
uv sync
uv tool install -e .
terminal-linux doctor
```

## Quick start

```bash
terminal-linux up
```

One terminal = live computer. Agents attach with MCP:

```bash
claude mcp add terminal-linux -- terminal-linux mcp default
terminal-linux plugins install --all
```

Headless:

```bash
terminal-linux up --no-view
terminal-linux action screenshot --output /tmp/guest.png
terminal-linux action run 'uname -a'
terminal-linux action open-url https://example.com
terminal-linux stop
```

**Ctrl+]** leaves the preview; the session keeps running. Reattach with `terminal-linux watch`.

![Agent workspace](assets/screenshot-workspace.png)

## Agent tools

| Tool | Purpose |
|------|---------|
| `status` / `up` / `stop` / `ls` | lifecycle |
| `workspace` | ensure agent-terminal + browser |
| `screenshot` | see the screen |
| `windows` / `focus` / `active_window` | window management |
| `open` / `open_url` | launch apps / URLs |
| `run_in_terminal` | shell commands in agent-terminal |
| `click` `move` `drag` `scroll` `type` `key` | input |
| `clipboard_get` / `clipboard_set` | guest clipboard |
| `wait` / `wait_stable` | timing |
| `cursor` | pointer position |

Docs: [docs/AGENT.md](docs/AGENT.md) · [docs/PLUGINS.md](docs/PLUGINS.md) · [skills/terminal-linux/SKILL.md](skills/terminal-linux/SKILL.md)

## License

MIT. Vendored Openbox under `vendor/openbox` remains GPL-2.0.
