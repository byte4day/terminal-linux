# Plugins & MCP

## Claude Code

This repo is a Claude Code marketplace + plugin:

| Path | Role |
|------|------|
| `.claude-plugin/marketplace.json` | Marketplace listing |
| `.claude-plugin/plugin.json` | Plugin manifest (MCP + skills) |
| `skills/terminal-linux/SKILL.md` | Agent skill |
| `.mcp.json` | Also loaded as plugin MCP config |

Install from GitHub:

```text
/plugin marketplace add byte4day/terminal-linux
/plugin install terminal-linux@terminal-linux
```

Or from a local checkout with an absolute path to this repo.

Requires `terminal-linux` on `PATH` (`uv tool install -e .` or your venv bin).

## Cursor

Project file: `.cursor/mcp.json`

User install:

```bash
terminal-linux plugins install --cursor
```

## VS Code / Copilot Chat

Use `mcp/vscode.json` (`servers` shape) or:

```bash
terminal-linux mcp --config --client vscode
```

## MCP tools

| Tool | Purpose |
|------|---------|
| `status` | Session readiness |
| `up` | Start desktop (optional `open_app_cmd`) |
| `stop` | Tear down session |
| `ls` | List sessions |
| `open` | Launch guest app |
| `screenshot` | Returns PNG image content |
| `click` / `move` / `drag` / `scroll` / `type` / `key` | Computer use |

Coordinates match the latest screenshot (top-left origin).
