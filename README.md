# terminal-linux

**A Linux desktop for AI agents — live in your terminal.**

`terminal-linux` boots a private desktop session, streams it into the terminal, and exposes MCP + CLI tools so agents can click, type, open apps, and run shell commands without touching your host pointer or screen.

Built by [byte4day](https://github.com/byte4day).

![terminal-linux desktop](assets/screenshot-desktop.png)

<p align="center"><img src="assets/screenshot-workspace.png" alt="agent-terminal" width="720" /></p>

## Features

- Live terminal preview (~20 fps) via a persistent capture stream (not a new screenshot process every frame)
- Visible **agent cursor** overlay so you can see where the agent is pointing
- **Multi-session tabs** — run several named desktops, switch in one terminal (`Alt+←/→`, `Alt+1-9`)
- Drive the same desktop yourself from the terminal (mouse + keys) while agents use MCP
- Own **agent-terminal** + **Firefox** workspace by default
- MCP tools for computer use: screenshot, click, type, windows, clipboard, wait, run_in_terminal, …
- `batch`: several steps in one call, one screenshot back
- Screenshots with a coordinate grid, a region crop and zoom for accurate clicks
- Agent skill ([Agent Skills](https://agentskills.io/)), a `terminal-linux` subagent and a Claude Code plugin marketplace
- One-terminal mode: keep `terminal-linux up` open; agents drive the same session over MCP
- Works with Claude Code, Cursor, Codex, and other Agent Skills hosts; prefer `inherit` / host default models (Claude computer-use: Opus or Fable when you pin)

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
uv tool install .
terminal-linux doctor
```

Or without cloning: `uv tool install git+https://github.com/byte4day/terminal-linux`. The vendored Openbox, the agent shell, the skill and the agent ship inside the package.

## Quick start

```bash
terminal-linux up
```

One terminal = live computer. Agents attach with MCP:

```bash
claude mcp add --scope user terminal-linux -- terminal-linux mcp default
terminal-linux plugins install --skill --agent
```

Or as a Claude Code plugin (MCP server, skill and agent in one step):

```text
/plugin install terminal-linux --marketplace byte4day/terminal-linux
```

Headless:

```bash
terminal-linux up --no-view --size 1920x1080
terminal-linux action screenshot --output /tmp/guest.png --grid
terminal-linux action run 'uname -a'
terminal-linux action open-url https://example.com
terminal-linux stop
```

**Ctrl+]** leaves the preview; the session keeps running. Reattach with `terminal-linux watch`.

### Multi-session tabs

```bash
terminal-linux up demo --no-view
terminal-linux up work --no-view
terminal-linux watch demo    # status bar shows tabs; Alt+←/→ or Alt+1-9 to switch
```

Each named session is its own Xvfb desktop. Agents attach with `terminal-linux mcp <name>`.

## Prompt for AI agents (setup)

Copy-paste this into Claude Code, Codex, or any coding agent:

```text
Set up terminal-linux for me on this Linux machine.

Repo: https://github.com/byte4day/terminal-linux
Branch: develop

Do this end-to-end without asking me to run commands manually unless something needs sudo or a login:

1. Clone the repo if needed (or use the current checkout), checkout develop, and create a fresh environment with `uv sync`.
2. Install the CLI on PATH with `uv tool install .` (or ensure `.venv/bin/terminal-linux` is usable).
3. Run `terminal-linux doctor` and install any missing host packages you can (Xvfb, xdotool, ImageMagick, wmctrl, xclip, openbox or use the vendored openbox, alacritty/kitty, firefox).
4. Install agent integrations: `terminal-linux plugins install --skill --agent` and wire MCP:
   `claude mcp add --scope user terminal-linux -- $(command -v terminal-linux) mcp default`
   (or print `terminal-linux mcp --config` and add it to my MCP client config).
5. Smoke-test headless:
   - `terminal-linux up demo --no-view`
   - `terminal-linux action demo windows` (expect agent-terminal + Firefox)
   - `terminal-linux action demo screenshot --output /tmp/terminal-linux-smoke.png`
   - `terminal-linux action demo run 'echo ok && uname -srm'`
   - `terminal-linux stop demo --force`
6. Tell me how to open the live preview (`terminal-linux up`) and how to drive it with MCP tools.
7. Do not push commits or change git remotes unless I ask.

If anything fails, fix it or report the exact blocker (missing sudo, missing package, unsupported terminal for live preview).
```

## Agent tools

| Tool | Purpose |
|------|---------|
| `status` / `up` / `stop` / `ls` | lifecycle |
| `workspace` | ensure agent-terminal + browser |
| `screenshot` | see the screen; `grid`, `region`, `zoom` for precise targets |
| `windows` / `focus` / `active_window` | titles, classes, geometry, focus by title or class |
| `open` / `open_url` | launch apps / URLs |
| `run_in_terminal` | shell commands in agent-terminal |
| `click` `move` `drag` `scroll` `type` `key` | input |
| `clipboard_get` / `clipboard_set` | guest clipboard |
| `wait` / `wait_stable` / `wait_window` | timing: fixed, until the screen settles, until a window appears or closes |
| `batch` | run a list of steps, get one screenshot |
| `cursor` | pointer position |

Action tools take `screenshot: true` to return the new screen with the result.

### New in 0.3

```bash
terminal-linux action NAME screenshot --grid --region 0,0,720,200 --zoom 2 --output top.png
terminal-linux action NAME wait-window --class firefox --timeout 20
terminal-linux action NAME windows            # now with x, y, width, height, center, active
terminal-linux action NAME key 'ctrl+a ctrl+c' # chord sequences; also super, ctrl++
terminal-linux batch NAME --steps '[{"action":"key","key":"ctrl+l"},{"action":"type","text":"example.com"},{"action":"key","key":"return"},{"action":"wait_stable"}]' --output page.png
```

Failures are JSON with a `code` (`not_running`, `out_of_bounds`, `bad_args`, `not_found`, `timeout`, `usage`). A point outside the screen is refused instead of clamped to the edge.

Docs: [docs/AGENT.md](docs/AGENT.md) · [docs/PLUGINS.md](docs/PLUGINS.md) · [skill](skills/terminal-linux/SKILL.md) · [agent](agents/claude/terminal-linux.md)

## License

MIT. Vendored Openbox under `src/terminal_linux/vendor/openbox` remains GPL-2.0.
