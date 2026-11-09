# Using terminal-linux

## MCP (recommended)

`terminal-linux mcp [NAME]` is a stdio Model Context Protocol server with computer-use tools: `status`, `up`, `stop`, `ls`, `open`, `screenshot` (returns the PNG), `click` (`clicks: 2|3`, `button: right`), `move`, `drag`, `scroll`, `type`, and `key`. Coordinates are pixels in the latest screenshot. Action tools accept `screenshot: true` to attach a fresh path.

```bash
claude mcp add terminal-linux -- /absolute/path/to/terminal-linux mcp default

# Or install the Claude Code plugin + Cursor configs
terminal-linux plugins install --all
```

Paste `terminal-linux mcp --config` (or `--client vscode`) into other MCP clients. See [PLUGINS.md](PLUGINS.md).

## Observe → act → verify

1. `terminal-linux status NAME` — start with `terminal-linux up NAME --no-view` if stopped.
2. `terminal-linux action NAME screenshot --output /tmp/guest.png` and inspect the PNG.
3. Act with click / type / key / scroll using that image's coordinates.
4. Screenshot again after each meaningful action.

All replies are JSON; failures exit nonzero.
