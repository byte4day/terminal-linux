# Plugins & MCP

## Claude Code

| Path | Role |
|------|------|
| `.claude-plugin/marketplace.json` | Marketplace |
| `.claude-plugin/plugin.json` | Plugin (MCP + skill + agent) |
| `skills/terminal-linux/SKILL.md` | Agent skill |
| `agents/claude/terminal-linux.md` | Desktop-operator subagent |
| `.mcp.json` | MCP config |

```text
/plugin marketplace add byte4day/terminal-linux
/plugin install terminal-linux@terminal-linux
```

Requires `terminal-linux` on `PATH` (`uv tool install .`).

## Without the plugin

```bash
terminal-linux plugins install --skill --agent   # ~/.claude/skills and ~/.claude/agents
claude mcp add --scope user terminal-linux -- terminal-linux mcp default
terminal-linux plugins status                    # what is installed and whether it is current
```

`plugins install` with no flags (or `--all`) also writes `~/.config/terminal-linux/mcp.json` and merges into a Claude Desktop config when one exists. It refuses to touch a config file it cannot parse.

The skill and the agent are single files in this repo. `src/terminal_linux/bundle/` links to them so the installed CLI carries the same text.

## Other MCP clients

```bash
terminal-linux mcp --config
terminal-linux mcp --config --client vscode
```

Configs also live under `mcp/`.

## MCP tools

See [AGENT.md](AGENT.md).
