# terminal-linux

A separate Linux desktop for computer-use agents, viewed and controlled from a terminal.

Inspired by [terminal-mac](https://github.com/govijr/terminal-mac): agents get a real GUI (browser, file manager, apps) without moving your host pointer or scraping your host screen. On Linux this uses **Xvfb + Openbox** instead of a full VM.

## What you get

- Private virtual display (`Xvfb`) with a lightweight window manager
- Terminal viewer that streams the desktop via **Kitty / Ghostty / WezTerm / iTerm2** graphics
- Agent CLI + **MCP** tools: `screenshot`, `click`, `drag`, `scroll`, `type`, `key`, `status`
- Input and screenshots only target the guest `DISPLAY` — not your host desktop

> This is **not** a full VM. Guest apps run as your user against a nested X server, so they share your home directory and network. For stronger isolation, run inside a container or dedicated user.

## Requirements

| Tool | Why |
|------|-----|
| Linux x86_64/arm64 | host |
| `Xvfb` | virtual display |
| `xdotool` | mouse/keyboard injection |
| ImageMagick (`import`, `convert`) | screenshots / wallpaper |
| `openbox` | window manager (system **or** `vendor/openbox` in this repo) |
| Kitty, Ghostty, WezTerm, or iTerm2 | inline terminal viewer |

Optional apps: `firefox`, `thunar`, `xterm`, …

## Install

```bash
# from this repo
uv sync
uv run terminal-linux doctor
```

Add a shim on your PATH if you like:

```bash
uv tool install -e .
# or: alias terminal-linux='uv run --directory /path/to/os-for-agents terminal-linux'
```

## Quick start

```bash
# Start a desktop and open the terminal viewer
terminal-linux up

# Or start headlessly for agents
terminal-linux up --no-view
terminal-linux open -- firefox
terminal-linux action screenshot --output /tmp/guest.png
terminal-linux action click 640 400
terminal-linux action type 'hello from the agent'
terminal-linux action key Return
terminal-linux stop
```

Viewer keys: **Ctrl+]** quit (session keeps running) · **Ctrl+G** shortcut palette · mouse clicks/drags/scroll map into the guest.

## Use with agents

### Claude Code plugin (MCP + skill)

```text
/plugin marketplace add byte4day/terminal-linux
/plugin install terminal-linux@terminal-linux
```

Or from a published clone:

```bash
claude mcp add terminal-linux -- terminal-linux mcp default
terminal-linux skills install
```

### One-shot local install (Cursor + Claude configs + skill)

```bash
uv sync && uv tool install -e .   # puts terminal-linux on PATH
terminal-linux plugins install --all
terminal-linux plugins status
```

### Config snippets

```bash
terminal-linux mcp --config                 # Claude / Cursor mcpServers shape
terminal-linux mcp --config --client vscode # VS Code servers shape
```

Checked-in configs: [`.mcp.json`](.mcp.json), [`.cursor/mcp.json`](.cursor/mcp.json), [`mcp/`](mcp/), [`.claude-plugin/`](.claude-plugin/).

MCP tools: `status`, `up`, `stop`, `ls`, `open`, `screenshot` (returns image), `click`, `move`, `drag`, `scroll`, `type`, `key`.

See [docs/AGENT.md](docs/AGENT.md) and [skills/terminal-linux/SKILL.md](skills/terminal-linux/SKILL.md).

## Lifecycle

```bash
terminal-linux ls
terminal-linux status default
terminal-linux view default
terminal-linux open default -- thunar
terminal-linux stop default
terminal-linux stop default --force
```

Customize size: `terminal-linux up work --width 1920 --height 1080 --no-view`.

Data lives under `~/.local/share/terminal-linux/machines/NAME/` (override with `TERMINAL_LINUX_HOME`).

## How it compares

| | [terminal-mac](https://github.com/govijr/terminal-mac) | **terminal-linux** |
|--|--|--|
| Guest | macOS VM (Virtualization.framework) | Xvfb + Openbox desktop |
| Isolation | Strong (separate OS) | Display-isolated; same user/FS |
| Viewer | Kitty/iTerm graphics | Same idea |
| Agent API | CLI + MCP | CLI + MCP (compatible shape) |

## Development

```bash
uv sync
uv run terminal-linux doctor
uv run terminal-linux up demo --no-view --open firefox
uv run terminal-linux action demo screenshot --output /tmp/demo.png
uv run terminal-linux stop demo
```

## License

MIT. Openbox is GPL-2.0; the optional vendored binary under `vendor/openbox` retains its upstream license.
