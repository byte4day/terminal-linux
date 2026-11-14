# Using terminal-linux

## MCP

`terminal-linux mcp [NAME]` is a stdio MCP server for the guest desktop.

```bash
claude mcp add --scope user terminal-linux -- terminal-linux mcp default
terminal-linux mcp --config          # print the config for other clients
```

Tools: `status`, `up`, `stop`, `ls`, `workspace`, `open`, `open_url`, `windows`, `focus`, `active_window`, `screenshot`, `click`, `move`, `drag`, `scroll`, `type`, `key`, `cursor`, `clipboard_get`, `clipboard_set`, `wait`, `wait_stable`, `wait_window`, `run_in_terminal`, `batch`.

Coordinates are pixels of the full screen (top-left origin). A point outside the screen returns `out_of_bounds`.

## Observe → act → verify

1. `status`, or `up` if stopped.
2. `screenshot` and inspect. `grid: true` adds labelled coordinate lines; `region` and `zoom` enlarge an area. Labels stay in full-screen pixels.
3. Prefer `windows` / `focus` / `run_in_terminal` / `key` when possible.
4. Otherwise `click` / `type` / `scroll` using screenshot coordinates.
5. Look again: `screenshot: true` on the action, `wait_stable`, or a new `screenshot`.

## Fewer round trips

`batch` runs steps in order and returns one screenshot. It stops at the first failing step.

```json
[
  {"action": "key", "key": "ctrl+l"},
  {"action": "type", "text": "example.com"},
  {"action": "key", "key": "return"},
  {"action": "wait_window", "title": "Example Domain", "timeout": 20},
  {"action": "wait_stable"}
]
```

Step actions: `click`, `move`, `drag`, `scroll`, `type`, `key`, `wait`, `wait_stable`, `wait_window`, `focus`, `open`, `open_url`, `run_in_terminal`, `clipboard_set`, `clipboard_get`. Arguments match the single tools.

## CLI

All CLI replies are JSON; failures exit nonzero with `error` and `code`. `NAME` defaults to `default`.

```bash
terminal-linux up NAME --no-view [--size 1920x1080]
terminal-linux action NAME screenshot --output shot.png [--grid] [--region X,Y,W,H --zoom 2]
terminal-linux action NAME wait-window --title 'Save As' [--class C] [--gone] --timeout 10
terminal-linux batch NAME --steps '<json>' | --file steps.json | --file -
terminal-linux stop NAME [--force]
```

## Subagent

`agents/claude/terminal-linux.md` is a Claude Code subagent that operates the guest and reports what the screen showed. Install it with `terminal-linux plugins install --agent`. It declares the MCP server inline, so it works without a global MCP entry.

## Safety

- Do not fall back to host screenshots or host input tools.
- Guest apps share the host user and filesystem by default.
- `stop --force` can lose guest work.
