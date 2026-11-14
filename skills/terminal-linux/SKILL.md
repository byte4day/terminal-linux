---
name: terminal-linux
description: Operate a separate Linux desktop (Xvfb) with screenshots, clicks, typing, windows and clipboard, without touching the user's own screen. Use when a task needs a real GUI: testing a desktop or web app, browsing, or any computer-use task that should stay sandboxed.
---

# terminal-linux

A private Linux desktop on its own X display, with a terminal titled **agent-terminal** and usually Firefox. Screenshots and input go only to that display. Never use host screenshot or input tools as a fallback.

The guest shares the host user, files and network. Only the display is isolated, so treat secrets and destructive commands as you would on the host.

## Loop

1. `status`. If not running, `up`.
2. `screenshot`. Every x/y is a pixel of the full screen, top-left origin.
3. Act: `click`, `type`, `key`, `scroll`, `drag`, or the shortcuts below.
4. Look again before the next decision. Stop the session when the task is done.

## Work in fewer round trips

- Pass `screenshot: true` on an action to get the new screen back with the result.
- `batch` runs a list of steps and returns one screenshot. It stops at the first failed step and says which.
- `wait_window` after `open` (returns the window's geometry). `wait_stable` after a page load or animation. Avoid fixed `wait` sleeps.
- `windows` lists title, class, position, size, center and which window is active. `focus` takes a title or class.
- `key` beats a small click target: `ctrl+l` (address bar), `ctrl+t`, `ctrl+w`, `alt+F4`, `alt+Tab`. Several chords at once: `ctrl+a ctrl+c`. `cmd` maps to `ctrl`.
- Long or exact text: `clipboard_set`, then `key ctrl+v`. Read text back with `key ctrl+c` and `clipboard_get`.
- `run_in_terminal` types a shell command into agent-terminal. Its output is on screen, not in the result.

## Aim precisely

- `screenshot` with `grid: true` overlays labelled coordinate lines.
- `region: [x, y, width, height]` crops, and `zoom: 2` to `4` enlarges, to read small text. Grid labels stay in full-screen pixels, so click with the numbers you read.
- A point outside the screen is refused (`out_of_bounds`) instead of clicked at the edge.

## MCP tools

`status` `up` `stop` `ls` `workspace` · `screenshot` · `click` `move` `drag` `scroll` `type` `key` · `windows` `active_window` `focus` `cursor` · `open` `open_url` `run_in_terminal` · `clipboard_get` `clipboard_set` · `wait` `wait_stable` `wait_window` · `batch`

## CLI (when the MCP tools are not loaded)

Every command prints JSON and exits nonzero on failure (`error`, `code`). `NAME` defaults to `default`.

```bash
terminal-linux up NAME --no-view [--size 1920x1080]
terminal-linux status NAME
terminal-linux action NAME screenshot --output shot.png [--grid] [--region X,Y,W,H --zoom 2]
terminal-linux action NAME click X Y [--double] [--button right] [--screenshot]
terminal-linux action NAME type 'literal text'
terminal-linux action NAME key 'ctrl+l'
terminal-linux action NAME scroll --dy -300 --x X --y Y
terminal-linux action NAME windows
terminal-linux action NAME focus --class firefox
terminal-linux action NAME wait-window --title 'Save As' --timeout 10
terminal-linux action NAME wait-stable
terminal-linux action NAME clipboard-set 'text'      # clipboard-get reads it
terminal-linux action NAME open-url https://example.com
terminal-linux action NAME run 'ls -la'
terminal-linux open NAME -- thunar
terminal-linux batch NAME --steps '[{"action":"key","key":"ctrl+l"},{"action":"type","text":"example.com"},{"action":"key","key":"return"},{"action":"wait_stable"}]' --output shot.png
terminal-linux stop NAME
```

Read the PNG at `path` / `screenshot` to see the screen.

## Setup

```bash
uv tool install git+https://github.com/byte4day/terminal-linux
terminal-linux doctor
claude mcp add --scope user terminal-linux -- terminal-linux mcp default
terminal-linux plugins install --skill --agent
```

Or as a Claude Code plugin: `/plugin marketplace add byte4day/terminal-linux`, then `/plugin install terminal-linux@terminal-linux`.

## If something fails

- `not_running`: call `up` (CLI: `up NAME --no-view`).
- `ready: false` with `wm_running: false`: `up` again restarts the window manager.
- A window will not close or the session is stuck: `stop` with `force: true`. This loses unsaved guest work.
