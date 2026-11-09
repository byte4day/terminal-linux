# Using terminal-linux

## MCP

`terminal-linux mcp [NAME]` is a stdio MCP server for the guest desktop.

```bash
claude mcp add terminal-linux -- /absolute/path/to/terminal-linux mcp default
terminal-linux plugins install --all
terminal-linux mcp --config
```

Tools include: `status`, `up`, `stop`, `ls`, `workspace`, `open`, `open_url`, `windows`, `focus`, `active_window`, `screenshot`, `click`, `move`, `drag`, `scroll`, `type`, `key`, `cursor`, `clipboard_get`, `clipboard_set`, `wait`, `wait_stable`, `run_in_terminal`.

Coordinates are pixels from the latest screenshot (top-left origin).

## Observe → act → verify

1. `status` — or `up` if stopped.
2. `screenshot` and inspect.
3. Prefer `windows` / `focus` / `run_in_terminal` / `key` when possible.
4. Otherwise `click` / `type` / `scroll` using screenshot coordinates.
5. `wait_stable` or screenshot again.

All CLI replies are JSON; failures exit nonzero.

## Safety

- Do not fall back to host screenshots or host input tools.
- Guest apps share the host user and filesystem by default.
- `stop --force` can lose guest work.
