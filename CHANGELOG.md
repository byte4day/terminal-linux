# Changelog

## 0.3.0 — 2026-11-14

### Added
- `batch` (MCP tool and `terminal-linux batch`): run a list of steps in one call and get one screenshot. Stops at the first failing step and names it.
- `wait_window` / `action wait-window`: wait for a window to appear or close, by title or class. Returns its geometry.
- `screenshot` options `grid`, `region` and `zoom`: labelled coordinate lines and enlarged crops, with labels in full-screen pixels.
- `windows` now reports x, y, width, height, center and which window is active. `focus` accepts a window class.
- `key` accepts chord sequences (`ctrl+a ctrl+c`), a lone modifier (`super`) and punctuation (`ctrl++`, `ctrl+-`).
- MCP action tools return the new screen as an image when called with `screenshot: true` (before: a file path).
- `up --size WxH`; `up` reports `reused` when the session was already running.
- Claude Code subagent `terminal-linux` (`agents/claude/terminal-linux.md`), installed by `plugins install --agent` and shipped in the plugin.
- `plugins status` shows whether the installed skill and agent are current.

### Fixed
- A non-editable install (`uv tool install .`, a wheel) had no Openbox, agent shell or skill: they lived outside the package. They now ship inside it.
- `up` took about 5 seconds longer than needed and never painted the wallpaper (`magick FILE x:root` blocks; replaced with `display -window root`).
- `action clipboard-set` hung any caller that read its output through a pipe, because the background `xclip` inherited stdout.
- A recycled or zombie pid could make a dead session report `running: true`. The saved pid must now be the Xvfb for that display.
- `stop` could leave Xvfb running with its state deleted. It now waits and escalates to SIGKILL, and never signals a pid it cannot tie to the session. `stop --force` used a `pkill` pattern that matched nothing.
- Two `up` calls at once could pick the same display. A stale X lock no longer blocks a display number.
- A window manager that died is restarted by `up`; `status` reports `wm_running`.
- Clicks outside the screen were clamped to the edge and reported as successful. They now fail with `out_of_bounds`.
- `action NAME wait 3` waited 1 second. `action click X Y` without a session name, `open -- CMD` without a name, non-numeric coordinates, a missing binary in `open`, and usage errors now give JSON instead of an argparse message or a traceback.
- `up`, `view` and `watch` from a process without a terminal (an agent) crashed in termios. `up` now starts the session and skips the viewer.
- `status`, `ls` and other reads no longer create a directory for a session name that does not exist. Stopped sessions are listed as `stopped`, not `unknown`. Session names are validated (no path separators).
- Session state and activity files are replaced atomically, so the live viewer no longer mistakes a half-written file for a stopped session.
- A key the guest rejects no longer ends the live viewer. The viewer's screenshot fallback no longer leaves one temp file per frame.
- `run_in_terminal` picks a terminal by window class, so a browser tab with "terminal" in its title is not typed into.
- `wait_stable` compares pixels with a small tolerance, so a blinking text cursor does not force a timeout.
- MCP screenshots no longer leave a PNG in `/tmp` on every call. CLI commands start in about 0.15 s instead of 0.7 s (the MCP package is imported only by `mcp`).
- `plugins install` no longer overwrites an MCP config file it cannot parse.
- `__version__` said 0.1.0.
- `doctor` marks which checks are required, so a missing optional tool is not read as a failure.

### Changed
- `vendor/openbox` moved to `src/terminal_linux/vendor/openbox`; `assets/agent-shell.sh` and `assets/alacritty-agent.toml` moved to `src/terminal_linux/assets/`.
- Install instruction is `uv tool install .` (editable mode is no longer required).

## 0.2.1 — 2026-11-10

### Fixed
- Live viewer no longer crashes on torn ffmpeg PNG frames (`SyntaxError: broken PNG file`).
- Capture now streams PNG frames over a pipe and publishes each complete frame with an atomic replace.

## 0.2.0 — 2026-11-10

### Changed
- Skill description tightened for Agent Skills catalogs.
- Docs note Agent Skills packaging and Claude Opus/Fable computer-use guidance without hard-pinning a model.
- Package / plugin version bumped to 0.2.0.
