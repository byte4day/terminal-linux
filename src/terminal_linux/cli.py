from __future__ import annotations

import argparse
import json
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any, NoReturn

from . import __version__, actions, agent_tools
from .errors import SessionError
from .jsonutil import emit, fail
from .session import list_sessions, open_app, parse_size, start_session, stop_session

ACTION_VERBS = [
    "status",
    "screenshot",
    "click",
    "move",
    "drag",
    "type",
    "key",
    "scroll",
    "windows",
    "focus",
    "active",
    "cursor",
    "clipboard-get",
    "clipboard-set",
    "open-url",
    "wait",
    "wait-stable",
    "wait-window",
    "run",
]


class JsonArgumentParser(argparse.ArgumentParser):
    """Usage errors as JSON on stdout (exit 2), like every other failure."""

    def error(self, message: str) -> NoReturn:
        fail(message, code="usage", exit_code=2, usage=self.format_usage().strip())


def _build_parser() -> argparse.ArgumentParser:
    p = JsonArgumentParser(
        prog="terminal-linux",
        description="A separate Linux desktop for computer-use agents, viewed from a terminal.",
    )
    p.add_argument("--version", action="version", version=f"terminal-linux {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def size_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--width", type=int, default=1280)
        sp.add_argument("--height", type=int, default=800)
        sp.add_argument("--size", default=None, metavar="WxH", help="e.g. 1920x1080 (overrides --width/--height)")

    up = sub.add_parser("up", help="start desktop + live terminal screen")
    up.add_argument("name", nargs="?", default="default")
    size_args(up)
    up.add_argument("--fps", type=float, default=20.0, help="live screen refresh rate")
    up.add_argument("--no-view", action="store_true", help="start session and print JSON only")
    up.add_argument("--detach", action="store_true", help="alias of --no-view")
    up.add_argument("--open", action="append", default=[], metavar="APP", help="launch APP inside the session (repeatable)")
    up.add_argument("--no-browser", action="store_true", help="don't auto-open firefox")
    up.add_argument("--no-terminal", action="store_true", help="don't auto-open agent-terminal")

    start = sub.add_parser("start", help="start a session without the viewer")
    start.add_argument("name", nargs="?", default="default")
    size_args(start)

    stop = sub.add_parser("stop", help="stop a session")
    stop.add_argument("name", nargs="?", default="default")
    stop.add_argument("--force", action="store_true")

    down = sub.add_parser("down", help="alias for stop")
    down.add_argument("name", nargs="?", default="default")
    down.add_argument("--force", action="store_true")

    status = sub.add_parser("status", help="session status (JSON)")
    status.add_argument("name", nargs="?", default="default")

    sub.add_parser("ls", help="list sessions")

    view = sub.add_parser("view", help="live terminal screen — watch the guest / agent")
    view.add_argument("name", nargs="?", default="default")
    view.add_argument("--fps", type=float, default=20.0)
    view.add_argument("--no-cursor", action="store_true", help="hide agent cursor overlay")

    watch = sub.add_parser("watch", help="alias for view (watch agent actions live)")
    watch.add_argument("name", nargs="?", default="default")
    watch.add_argument("--fps", type=float, default=20.0)
    watch.add_argument("--no-cursor", action="store_true", help="hide agent cursor overlay")

    open_p = sub.add_parser("open", help="launch a command inside the session")
    open_p.add_argument("name", nargs="?", default="default")
    open_p.add_argument("command", nargs=argparse.REMAINDER, help="command after --")

    workspace = sub.add_parser("workspace", help="open agent-terminal + firefox for AI use")
    workspace.add_argument("name", nargs="?", default="default")
    workspace.add_argument("--no-browser", action="store_true")
    workspace.add_argument("--no-terminal", action="store_true")

    action = sub.add_parser("action", help="computer-use actions (JSON)")
    action.add_argument("name", nargs="?", default="default")
    action.add_argument("verb", choices=ACTION_VERBS)
    action.add_argument("args", nargs="*")
    action.add_argument("--output", type=Path)
    action.add_argument("--grid", action="store_true", help="screenshot: overlay labelled coordinate lines")
    action.add_argument("--region", default=None, metavar="X,Y,W,H", help="screenshot: crop to this area")
    action.add_argument("--zoom", type=int, default=1, help="screenshot: enlarge 1-4x (with --region)")
    action.add_argument("--double", action="store_true")
    action.add_argument("--button", default="left", choices=["left", "middle", "right"])
    action.add_argument("--text", default=None)
    action.add_argument("--dx", type=int, default=0)
    action.add_argument("--dy", type=int, default=0)
    action.add_argument("--x", type=int, default=None)
    action.add_argument("--y", type=int, default=None)
    action.add_argument("--title", default=None, help="window title substring (focus, wait-window)")
    action.add_argument("--class", dest="window_class", default=None, help="window class substring (focus, wait-window)")
    action.add_argument("--id", dest="window_id", default=None, help="window id for focus")
    action.add_argument("--gone", action="store_true", help="wait-window: wait for the window to close")
    action.add_argument("--seconds", type=float, default=None)
    action.add_argument("--timeout", type=float, default=10.0)
    action.add_argument("--screenshot", action="store_true", help="return a fresh screenshot path")

    batch = sub.add_parser("batch", help="run several action steps from JSON, then one screenshot")
    batch.add_argument("name", nargs="?", default="default")
    src = batch.add_mutually_exclusive_group(required=True)
    src.add_argument("--steps", default=None, help='JSON list, e.g. \'[{"action":"key","key":"ctrl+l"}]\'')
    src.add_argument("--file", default=None, help="file holding the JSON list ('-' reads stdin)")
    batch.add_argument("--output", type=Path, help="where to save the final screenshot")
    batch.add_argument("--no-screenshot", action="store_true")

    mcp = sub.add_parser("mcp", help="run MCP server (stdio) or print client config")
    mcp.add_argument("name", nargs="?", default="default")
    mcp.add_argument("--config", action="store_true", help="print MCP client config JSON and exit")
    mcp.add_argument(
        "--client",
        default="claude",
        choices=["claude", "generic", "vscode"],
        help="config shape for --config (default: claude)",
    )

    skills = sub.add_parser("skills", help="agent skill helpers")
    skills_sub = skills.add_subparsers(dest="skills_cmd", required=True)
    skills_sub.add_parser("get", help="print the agent skill markdown")
    skills_install = skills_sub.add_parser("install", help="install skill into a skills directory")
    skills_install.add_argument("--dir", type=Path, default=None)

    plugins = sub.add_parser("plugins", help="install skill, agent and MCP client configs")
    plugins_sub = plugins.add_subparsers(dest="plugins_cmd", required=True)
    plugins_sub.add_parser("status", help="show plugin / MCP install status")
    plug_install = plugins_sub.add_parser("install", help="install skill + agent + MCP configs")
    plug_install.add_argument("--user-mcp", action="store_true", help="write ~/.config/terminal-linux/mcp.json")
    plug_install.add_argument("--claude", action="store_true", help="merge into Claude Desktop MCP config")
    plug_install.add_argument("--skill", action="store_true", help="install agent skill")
    plug_install.add_argument("--agent", action="store_true", help="install the Claude Code subagent")
    plug_install.add_argument("--all", action="store_true", help="skill + agent + user MCP + claude")
    plug_install.add_argument("--dir", type=Path, default=None, help="skills directory override")
    plug_install.add_argument("--agents-dir", type=Path, default=None, help="agents directory override")

    sub.add_parser("doctor", help="check host dependencies")

    return p


def normalize_argv(argv: list[str]) -> list[str]:
    """Let NAME be omitted where argparse alone cannot tell.

    `action click 10 20` → `action default click 10 20`
    `open -- firefox`    → `open default -- firefox`
    """
    argv = list(argv)
    if len(argv) >= 2 and argv[0] == "action" and argv[1] in ACTION_VERBS:
        # `action status` is ambiguous only if a session is literally named like a verb.
        if not (len(argv) >= 3 and argv[2] in ACTION_VERBS):
            argv.insert(1, "default")
    if len(argv) >= 2 and argv[0] == "open" and argv[1] == "--":
        argv.insert(1, "default")
    return argv


def _ints(values: list[str], count: int, usage: str) -> list[int]:
    if len(values) < count:
        fail(f"usage: {usage}", code="usage", exit_code=2)
    try:
        return [int(v) for v in values[:count]]
    except ValueError:
        fail(f"coordinates must be whole numbers; usage: {usage}", code="bad_args")


def _handle_action(ns: argparse.Namespace) -> None:
    from .session import get_running

    name = ns.name
    if ns.verb == "status":
        emit(actions.status_payload(name))
    if ns.verb == "windows":
        emit({"ok": True, "windows": agent_tools.list_windows(name)})
    if ns.verb == "active":
        emit({"ok": True, **agent_tools.active_window(name)})
    if ns.verb == "focus":
        wid = ns.window_id
        title = ns.title
        if ns.args:
            token = ns.args[0]
            if wid is None and len(ns.args) == 1 and (token.startswith("0x") or token.isdigit()):
                wid = token
            elif title is None:
                title = " ".join(ns.args)
        emit(agent_tools.focus_window(name, window_id=wid, title=title, cls=ns.window_class))
    if ns.verb == "cursor":
        emit(agent_tools.cursor_position(name))
    if ns.verb == "clipboard-get":
        emit(agent_tools.clipboard_get(name))
    if ns.verb == "clipboard-set":
        text = ns.text if ns.text is not None else " ".join(ns.args)
        emit(agent_tools.clipboard_set(name, text))
    if ns.verb == "open-url":
        url = ns.args[0] if ns.args else (ns.text or "")
        if not url:
            fail("usage: action NAME open-url URL", code="usage", exit_code=2)
        emit(agent_tools.open_url(name, url))
    if ns.verb == "wait":
        seconds = ns.seconds
        if seconds is None:
            try:
                seconds = float(ns.args[0]) if ns.args else 1.0
            except ValueError:
                fail("usage: action NAME wait SECONDS", code="bad_args")
        emit(agent_tools.wait(name, seconds))
    if ns.verb == "wait-stable":
        emit(agent_tools.wait_stable(name, timeout=ns.timeout))
    if ns.verb == "wait-window":
        title = ns.title if ns.title is not None else (" ".join(ns.args) or None)
        result = agent_tools.wait_window(
            name, title=title, cls=ns.window_class, timeout=ns.timeout, gone=ns.gone
        )
        emit(result, exit_code=1 if result.get("timeout") else 0)
    if ns.verb == "run":
        cmd = ns.text if ns.text is not None else " ".join(ns.args)
        if not cmd:
            fail("usage: action NAME run 'shell command'", code="usage", exit_code=2)
        result = agent_tools.run_in_terminal(name, cmd)
        if ns.screenshot:
            result["screenshot"] = str(actions.screenshot(get_running(name)))
        emit(result)

    state = get_running(name)

    def maybe_shot(payload: dict) -> dict:
        if ns.screenshot:
            payload["screenshot"] = str(actions.screenshot(state))
        return payload

    if ns.verb == "screenshot":
        path = actions.screenshot(state, ns.output, region=ns.region, grid=ns.grid, zoom=ns.zoom)
        payload: dict[str, Any] = {"ok": True, "path": str(path), "width": state.width, "height": state.height}
        if ns.region:
            payload["region"] = ns.region
        if ns.grid:
            payload["grid"] = True
        if ns.region or ns.zoom > 1:
            payload["note"] = "grid labels and click coordinates are full-screen pixels"
        emit(payload)

    if ns.verb == "click":
        usage = "action NAME click X Y [--double] [--button right]"
        x, y = _ints(ns.args, 2, usage)
        clicks = 2 if ns.double else 1
        if len(ns.args) >= 3:
            clicks = _ints(ns.args[2:], 1, usage)[0]
        actions.click(state, x, y, button=ns.button, clicks=clicks)
        emit(maybe_shot({"ok": True, "x": x, "y": y, "button": ns.button, "clicks": clicks}))

    if ns.verb == "move":
        x, y = _ints(ns.args, 2, "action NAME move X Y")
        actions.move(state, x, y)
        emit(maybe_shot({"ok": True, "x": x, "y": y}))

    if ns.verb == "drag":
        x1, y1, x2, y2 = _ints(ns.args, 4, "action NAME drag X Y X2 Y2")
        actions.drag(state, x1, y1, x2, y2)
        emit(maybe_shot({"ok": True, "from": [x1, y1], "to": [x2, y2]}))

    if ns.verb == "type":
        text = ns.text
        if text is None:
            text = " ".join(ns.args) if ns.args else ""
        actions.type_text(state, text)
        emit(maybe_shot({"ok": True, "chars": len(text)}))

    if ns.verb == "key":
        if not ns.args:
            fail("usage: action NAME key KEYSPEC", code="usage", exit_code=2)
        keyspec = " ".join(ns.args)
        actions.press_key(state, keyspec)
        emit(maybe_shot({"ok": True, "key": keyspec}))

    if ns.verb == "scroll":
        x, y = ns.x, ns.y
        if x is None and y is None and len(ns.args) >= 2:
            x, y = _ints(ns.args, 2, "action NAME scroll --dy N [--x X --y Y]")
        if not ns.dy and not ns.dx:
            fail("scroll needs --dy and/or --dx (negative --dy scrolls down)", code="bad_args")
        actions.scroll(state, dy=ns.dy, dx=ns.dx, x=x, y=y)
        emit(maybe_shot({"ok": True, "dy": ns.dy, "dx": ns.dx, "x": x, "y": y}))

    fail(f"unknown verb {ns.verb}")


def _handle_batch(ns: argparse.Namespace) -> None:
    from .batch import run_batch
    from .session import get_running

    if ns.file == "-":
        raw = sys.stdin.read()
    elif ns.file:
        try:
            raw = Path(ns.file).expanduser().read_text()
        except OSError as exc:
            fail(f"cannot read {ns.file}: {exc.strerror}", code="bad_args")
    else:
        raw = ns.steps
    try:
        steps = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"steps are not valid JSON: {exc}", code="bad_args")
    result = run_batch(ns.name, steps)
    if not ns.no_screenshot:
        try:
            result["screenshot"] = str(actions.screenshot(get_running(ns.name), ns.output))
        except SessionError as exc:
            result["screenshot_error"] = str(exc)
    emit(result, exit_code=0 if result["ok"] else 1)


def _split_app(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError as exc:
        raise SessionError(f"cannot parse --open {text!r}: {exc}", code="bad_args") from exc


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Allow `terminal-linux` with no args → up
    if not argv:
        argv = ["up"]

    try:
        ns = _build_parser().parse_args(normalize_argv(argv))
        _dispatch(ns)
    except SessionError as exc:
        fail(str(exc), code=exc.code)
    except KeyboardInterrupt:
        fail("interrupted", code="interrupted", exit_code=130)
    except BrokenPipeError:
        raise SystemExit(1) from None
    except Exception as exc:  # noqa: BLE001 - the contract is JSON out, never a traceback
        fail(f"{type(exc).__name__}: {exc}", code="internal_error")


def _dispatch(ns: argparse.Namespace) -> None:
    if ns.cmd in {"up", "start"}:
        width, height = (ns.width, ns.height) if not ns.size else parse_size(ns.size)
        apps = [_split_app(app) for app in getattr(ns, "open", []) or []]
        headless = ns.cmd == "start" or getattr(ns, "no_view", False) or getattr(ns, "detach", False)
        note = None
        if not headless and not (sys.stdin.isatty() and sys.stdout.isatty()):
            # An agent or a pipe ran `up`: there is no terminal to draw the live view in.
            headless = True
            note = "no terminal attached, so the live view was skipped; the session is running"
        before = actions.status_payload(ns.name)
        # Default AI workspace: own terminal + browser (unless user passed --open).
        if not apps and not before["running"]:
            if not getattr(ns, "no_terminal", False):
                try:
                    apps.append(agent_tools.pick_guest_terminal())
                except SessionError:
                    pass
            if not getattr(ns, "no_browser", False) and shutil.which("firefox"):
                apps.append(["firefox"])
        state = start_session(ns.name, width=width, height=height, apps=apps)
        payload: dict[str, Any] = {
            "ok": True,
            "name": state.name,
            "display": state.display_name,
            "width": state.width,
            "height": state.height,
            "xvfb_pid": state.xvfb_pid,
            "wm_pid": state.wm_pid,
            "reused": bool(before["running"]),
        }
        if note:
            payload["note"] = note
        if headless:
            emit(payload)
        from .viewer import run_viewer

        print(json.dumps(payload, indent=2), file=sys.stderr)
        print(
            "ONE TERMINAL MODE: this terminal IS the live computer preview.\n"
            "Keep it open. MCP clients drive it via MCP — "
            f"no second pane needed (session={ns.name}).\n"
            "Ctrl+] exits the preview; desktop keeps running.",
            file=sys.stderr,
        )
        raise SystemExit(
            run_viewer(
                ns.name,
                fps=getattr(ns, "fps", 20.0),
                show_cursor_overlay=not getattr(ns, "no_cursor", False),
            )
        )

    if ns.cmd in {"stop", "down"}:
        was_running = stop_session(ns.name, force=ns.force)
        emit({"ok": True, "stopped": ns.name, "force": ns.force, "was_running": was_running})

    if ns.cmd == "status":
        emit(actions.status_payload(ns.name))

    if ns.cmd == "ls":
        emit({"ok": True, "sessions": list_sessions()})

    if ns.cmd in {"view", "watch"}:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            fail(
                "the live view needs an interactive terminal; "
                "agents should use `action NAME screenshot` instead",
                code="no_tty",
            )
        from .viewer import run_viewer

        raise SystemExit(run_viewer(ns.name, fps=ns.fps, show_cursor_overlay=not ns.no_cursor))

    if ns.cmd == "open":
        cmd = list(ns.command)
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]
        if not cmd:
            fail("usage: terminal-linux open [NAME] -- COMMAND...", code="usage", exit_code=2)
        pid = open_app(ns.name, cmd)
        emit({"ok": True, "pid": pid, "command": cmd})

    if ns.cmd == "workspace":
        emit(
            agent_tools.ensure_agent_workspace(
                ns.name,
                browser=not ns.no_browser,
                terminal=not ns.no_terminal,
            )
        )

    if ns.cmd == "action":
        _handle_action(ns)

    if ns.cmd == "batch":
        _handle_batch(ns)

    if ns.cmd == "mcp":
        from .mcp_server import mcp_config_snippet, run_mcp
        from .paths import validate_name

        validate_name(ns.name)
        if ns.config:
            emit(mcp_config_snippet(ns.name, client=ns.client))
        run_mcp(ns.name)
        return

    if ns.cmd == "skills":
        from . import plugins

        if ns.skills_cmd == "get":
            sys.stdout.write(plugins.skill_text())
            return
        if ns.skills_cmd == "install":
            emit({"ok": True, "path": str(plugins.install_skill(ns.dir))})

    if ns.cmd == "plugins":
        from . import plugins

        if ns.plugins_cmd == "status":
            emit(plugins.plugin_status())
        if ns.plugins_cmd == "install":
            picked = ns.user_mcp or ns.claude or ns.skill or ns.agent
            do_all = ns.all or not picked
            results: dict[str, str] = {}
            if do_all or ns.skill:
                results["skill"] = str(plugins.install_skill(ns.dir))
            if do_all or ns.agent:
                results["agent"] = str(plugins.install_agent(ns.agents_dir))
            if do_all or ns.user_mcp:
                results["user_mcp"] = str(plugins.install_user_mcp())
            if do_all or ns.claude:
                results["claude"] = str(plugins.install_claude_mcp())
            emit({**plugins.plugin_status(), "installed": results})

    if ns.cmd == "doctor":
        from .doctor import run_doctor

        report = run_doctor()
        emit(report, exit_code=0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
