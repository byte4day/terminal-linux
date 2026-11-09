---
name: terminal-linux
description: Operate a separate Linux desktop (Xvfb + window manager) with screenshots, clicks, typing and shortcuts, without touching the user's own desktop. Use when a task needs a real Linux GUI — testing an app, browsing, or any computer-use task the user wants sandboxed.
---

# terminal-linux

`terminal-linux` runs a real Linux desktop on a private Xvfb display. Screenshots and input go only to that display. It never controls the user's host desktop.

## Prefer the MCP tools

If tools from the `terminal-linux` MCP server are available, use them:

1. `status` — session running and `ready` is true. If not, call `up` (optionally with `open_app_cmd: "firefox"`).
2. `screenshot` — every x/y for other tools is a pixel in this image (top-left origin). The tool returns the image itself.
3. Act with `click` (`clicks: 2`, `button: "right"`), `move`, `drag`, `scroll` (negative `dy` scrolls down), `type` (literal text), or `key` (`return`, `tab`, `escape`, `ctrl+c`, `alt+F4`, `cmd+space` — `cmd` maps to `ctrl`).
4. Launch apps with `open` (`"firefox"`, `"thunar"`, …).
5. Look again: pass `screenshot: true` on an action, or call `screenshot`, before the next step.
6. `stop` when finished (use `force: true` only if needed).

Prefer keyboard shortcuts over hunting for small targets.

## Without MCP: the CLI

Every command prints JSON and exits nonzero on failure. `NAME` defaults to `default`.

```bash
terminal-linux status NAME
terminal-linux up NAME --no-view
terminal-linux open NAME -- firefox
terminal-linux action NAME screenshot --output /tmp/guest.png
terminal-linux action NAME click X Y [--double] [--button right]
terminal-linux action NAME move X Y
terminal-linux action NAME drag X Y X2 Y2
terminal-linux action NAME type 'literal text'
terminal-linux action NAME key ctrl+c
terminal-linux action NAME scroll --dy -300 --x X --y Y
terminal-linux stop NAME
```

## Plugins

```bash
# Claude Code marketplace plugin
/plugin marketplace add byte4day/terminal-linux
/plugin install terminal-linux@terminal-linux

# Or wire MCP + skill manually
terminal-linux plugins install --all
claude mcp add terminal-linux -- terminal-linux mcp default
```

## Safety

- Never fall back to host screenshots or host input tools.
- Guest apps share the host filesystem/user by default — treat secrets carefully.
- `stop --force` / `force: true` can lose guest work.
