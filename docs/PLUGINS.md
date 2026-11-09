# Plugins & MCP

## Claude Code

| Path | Role |
|------|------|
| `.claude-plugin/marketplace.json` | Marketplace |
| `.claude-plugin/plugin.json` | Plugin (MCP + skills) |
| `skills/terminal-linux/SKILL.md` | Agent skill |
| `.mcp.json` | MCP config |

```text
/plugin marketplace add byte4day/terminal-linux
/plugin install terminal-linux@terminal-linux
```

Requires `terminal-linux` on `PATH` (`uv tool install -e .`).

## Other MCP clients

```bash
terminal-linux mcp --config
terminal-linux mcp --config --client vscode
terminal-linux plugins install --all
```

Configs also live under `mcp/`.

## MCP tools

See [AGENT.md](AGENT.md).
