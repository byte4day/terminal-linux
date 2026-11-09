from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__, actions, agent_tools
from .doctor import run_doctor
from .jsonutil import emit, fail
from .mcp_server import mcp_config_snippet, run_mcp
from .plugins import install_claude_mcp, install_skill, install_user_mcp, plugin_status
from .session import (
    SessionError,
    list_sessions,
    open_app,
    start_session,
    stop_session,
)
from .viewer import run_viewer


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="terminal-linux",
        description="A separate Linux desktop for computer-use agents, viewed from a terminal.",
    )
    p.add_argument("--version", action="version", version=f"terminal-linux {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("up", help="start desktop + live terminal screen (live terminal screen)")
    up.add_argument("name", nargs="?", default="default")
    up.add_argument("--width", type=int, default=1280)
    up.add_argument("--height", type=int, default=800)
    up.add_argument("--fps", type=float, default=12.0, help="live screen refresh rate")
    up.add_argument("--no-view", action="store_true", help="start session and print JSON only")
    up.add_argument("--detach", action="store_true", help="alias of --no-view")
    up.add_argument("--open", action="append", default=[], metavar="APP", help="launch APP inside the session (repeatable)")
    up.add_argument("--no-browser", action="store_true", help="don't auto-open firefox")
    up.add_argument("--no-terminal", action="store_true", help="don't auto-open agent-terminal")

    start = sub.add_parser("start", help="start a session without the viewer")
    start.add_argument("name", nargs="?", default="default")
    start.add_argument("--width", type=int, default=1280)
    start.add_argument("--height", type=int, default=800)

    stop = sub.add_parser("stop", help="stop a session")
    stop.add_argument("name", nargs="?", default="default")
    stop.add_argument("--force", action="store_true")

    down = sub.add_parser("down", help="alias for stop")
    down.add_argument("name", nargs="?", default="default")
    down.add_argument("--force", action="store_true")

    status = sub.add_parser("status", help="session status (JSON)")
    status.add_argument("name", nargs="?", default="default")

    ls = sub.add_parser("ls", help="list sessions")

    view = sub.add_parser("view", help="live terminal screen — watch the guest / agent")
    view.add_argument("name", nargs="?", default="default")
    view.add_argument("--fps", type=float, default=12.0)

    watch = sub.add_parser("watch", help="alias for view (watch agent actions live)")
    watch.add_argument("name", nargs="?", default="default")
    watch.add_argument("--fps", type=float, default=12.0)

    open_p = sub.add_parser("open", help="launch a command inside the session")
    open_p.add_argument("name", nargs="?", default="default")
    open_p.add_argument("command", nargs=argparse.REMAINDER, help="command after --")

    workspace = sub.add_parser("workspace", help="open agent-terminal + firefox for AI use")
    workspace.add_argument("name", nargs="?", default="default")
    workspace.add_argument("--no-browser", action="store_true")
    workspace.add_argument("--no-terminal", action="store_true")

    action = sub.add_parser("action", help="computer-use actions (JSON)")
    action.add_argument("name", nargs="?", default="default")
    action.add_argument(
        "verb",
        choices=[
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
            "run",
        ],
    )
    action.add_argument("args", nargs="*")
    action.add_argument("--output", type=Path)
    action.add_argument("--double", action="store_true")
    action.add_argument("--button", default="left", choices=["left", "middle", "right"])
    action.add_argument("--text", default=None)
    action.add_argument("--dx", type=int, default=0)
    action.add_argument("--dy", type=int, default=0)
    action.add_argument("--x", type=int, default=None)
    action.add_argument("--y", type=int, default=None)
    action.add_argument("--title", default=None, help="window title substring for focus")
    action.add_argument("--id", dest="window_id", default=None, help="window id for focus")
    action.add_argument("--seconds", type=float, default=1.0)
    action.add_argument("--timeout", type=float, default=10.0)
    action.add_argument("--screenshot", action="store_true", help="return a fresh screenshot path")

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
    skills_get = skills_sub.add_parser("get", help="print the agent skill markdown")
    skills_get.add_argument("--dir", type=Path, default=None)
    skills_install = skills_sub.add_parser("install", help="install skill into a skills directory")
    skills_install.add_argument("--dir", type=Path, default=None)

    plugins = sub.add_parser("plugins", help="install MCP client + skill plugin pieces")
    plugins_sub = plugins.add_subparsers(dest="plugins_cmd", required=True)
    plugins_sub.add_parser("status", help="show plugin / MCP install status")
    plug_install = plugins_sub.add_parser("install", help="install skill + MCP configs")
    plug_install.add_argument("--user-mcp", action="store_true", help="write ~/.config/terminal-linux/mcp.json")
    plug_install.add_argument("--claude", action="store_true", help="merge into Claude MCP config")
    plug_install.add_argument("--skill", action="store_true", help="install agent skill")
    plug_install.add_argument("--all", action="store_true", help="install skill + user MCP + claude")
    plug_install.add_argument("--dir", type=Path, default=None, help="skills directory override")

    sub.add_parser("doctor", help="check host dependencies")

    return p


def _skill_text() -> str:
    root = Path(__file__).resolve().parents[2]
    path = root / "skills" / "terminal-linux" / "SKILL.md"
    if path.exists():
        return path.read_text()
    return "# terminal-linux\n\nSee README.md for agent usage.\n"


def _handle_action(ns: argparse.Namespace) -> None:
    from .session import get_running

    if ns.verb == "status":
        emit(actions.status_payload(ns.name))

    # Verbs that don't need a preloaded state object beyond name
    if ns.verb == "windows":
        emit({"ok": True, "windows": agent_tools.list_windows(ns.name)})
    if ns.verb == "active":
        emit({"ok": True, **agent_tools.active_window(ns.name)})
    if ns.verb == "focus":
        wid = ns.window_id
        title = ns.title
        if ns.args:
            token = ns.args[0]
            if wid is None and (token.startswith("0x") or token.isdigit()):
                wid = token
            elif title is None:
                title = " ".join(ns.args)
        emit(agent_tools.focus_window(ns.name, window_id=wid, title=title))
    if ns.verb == "cursor":
        emit(agent_tools.cursor_position(ns.name))
    if ns.verb == "clipboard-get":
        emit(agent_tools.clipboard_get(ns.name))
    if ns.verb == "clipboard-set":
        text = ns.text if ns.text is not None else " ".join(ns.args)
        emit(agent_tools.clipboard_set(ns.name, text))
    if ns.verb == "open-url":
        url = ns.args[0] if ns.args else (ns.text or "")
        if not url:
            fail("usage: action NAME open-url URL")
        emit(agent_tools.open_url(ns.name, url))
    if ns.verb == "wait":
        emit(agent_tools.wait(ns.name, ns.seconds if ns.seconds is not None else float(ns.args[0] if ns.args else 1)))
    if ns.verb == "wait-stable":
        emit(agent_tools.wait_stable(ns.name, timeout=ns.timeout))
    if ns.verb == "run":
        cmd = ns.text if ns.text is not None else " ".join(ns.args)
        if not cmd:
            fail("usage: action NAME run 'shell command'")
        emit(agent_tools.run_in_terminal(ns.name, cmd))

    try:
        state = get_running(ns.name)
    except SessionError as exc:
        fail(str(exc), code="not_running")

    def maybe_shot(payload: dict) -> dict:
        if ns.screenshot:
            path = actions.screenshot(state)
            payload["screenshot"] = str(path)
        return payload

    if ns.verb == "screenshot":
        path = actions.screenshot(state, ns.output)
        emit({"ok": True, "path": str(path), "width": state.width, "height": state.height})

    if ns.verb == "click":
        if len(ns.args) < 2:
            fail("usage: action NAME click X Y [--double] [--button right]")
        x, y = int(ns.args[0]), int(ns.args[1])
        clicks = 2 if ns.double else 1
        if len(ns.args) >= 3:
            clicks = int(ns.args[2])
        actions.click(state, x, y, button=ns.button, clicks=clicks)
        emit(maybe_shot({"ok": True, "x": x, "y": y, "button": ns.button, "clicks": clicks}))

    if ns.verb == "move":
        if len(ns.args) < 2:
            fail("usage: action NAME move X Y")
        x, y = int(ns.args[0]), int(ns.args[1])
        actions.move(state, x, y)
        emit(maybe_shot({"ok": True, "x": x, "y": y}))

    if ns.verb == "drag":
        if len(ns.args) < 4:
            fail("usage: action NAME drag X Y X2 Y2")
        x1, y1, x2, y2 = map(int, ns.args[:4])
        actions.drag(state, x1, y1, x2, y2)
        emit(maybe_shot({"ok": True, "from": [x1, y1], "to": [x2, y2]}))

    if ns.verb == "type":
        text = ns.text
        if text is None:
            text = " ".join(ns.args) if ns.args else ""
        actions.type_text(state, text)
        emit(maybe_shot({"ok": True, "text": text}))

    if ns.verb == "key":
        if not ns.args:
            fail("usage: action NAME key KEYSPEC")
        keyspec = ns.args[0]
        actions.press_key(state, keyspec)
        emit(maybe_shot({"ok": True, "key": keyspec}))

    if ns.verb == "scroll":
        x = ns.x if ns.x is not None else (int(ns.args[0]) if len(ns.args) >= 1 else None)
        y = ns.y if ns.y is not None else (int(ns.args[1]) if len(ns.args) >= 2 else None)
        # allow --x/--y via flags; positional optional
        if ns.x is not None:
            x = ns.x
        if ns.y is not None:
            y = ns.y
        actions.scroll(state, dy=ns.dy, dx=ns.dx, x=x, y=y)
        emit(maybe_shot({"ok": True, "dy": ns.dy, "dx": ns.dx, "x": x, "y": y}))

    fail(f"unknown verb {ns.verb}")


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Allow `terminal-linux` with no args → up
    if not argv:
        argv = ["up"]

    parser = _build_parser()
    # Make `open -- cmd` and `open cmd` both work: strip leading -- from remainder
    ns = parser.parse_args(argv)

    try:
        if ns.cmd in {"up", "start"}:
            apps = []
            for app in getattr(ns, "open", []) or []:
                apps.append(app.split())
            headless = ns.cmd == "start" or getattr(ns, "no_view", False) or getattr(ns, "detach", False)
            # Default AI workspace: own terminal + browser (unless user passed --open).
            if not apps:
                if not getattr(ns, "no_terminal", False):
                    try:
                        apps.append(agent_tools.pick_guest_terminal())
                    except SessionError:
                        pass
                if not getattr(ns, "no_browser", False) and shutil.which("firefox"):
                    apps.append(["firefox"])
            state = start_session(ns.name, width=ns.width, height=ns.height, apps=apps)
            payload = {
                "ok": True,
                "name": state.name,
                "display": state.display_name,
                "width": state.width,
                "height": state.height,
                "xvfb_pid": state.xvfb_pid,
                "wm_pid": state.wm_pid,
            }
            if headless:
                emit(payload)
            print(json.dumps(payload, indent=2), file=sys.stderr)
            print(
                "ONE TERMINAL MODE: this terminal IS the live computer preview.\n"
                "Keep it open. MCP clients drive it via MCP — "
                f"no second pane needed (session={ns.name}).\n"
                "Ctrl+] exits the preview; desktop keeps running.",
                file=sys.stderr,
            )
            raise SystemExit(run_viewer(ns.name, fps=getattr(ns, "fps", 12.0)))

        if ns.cmd in {"stop", "down"}:
            stop_session(ns.name, force=ns.force)
            emit({"ok": True, "stopped": ns.name, "force": ns.force})

        if ns.cmd == "status":
            emit(actions.status_payload(ns.name))

        if ns.cmd == "ls":
            emit({"ok": True, "sessions": list_sessions()})

        if ns.cmd in {"view", "watch"}:
            raise SystemExit(run_viewer(ns.name, fps=ns.fps))

        if ns.cmd == "open":
            cmd = list(ns.command)
            if cmd and cmd[0] == "--":
                cmd = cmd[1:]
            if not cmd:
                fail("usage: terminal-linux open [NAME] -- COMMAND...")
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

        if ns.cmd == "mcp":
            if ns.config:
                emit(mcp_config_snippet(ns.name, client=ns.client))
            run_mcp(ns.name)
            return

        if ns.cmd == "skills":
            text = _skill_text()
            if ns.skills_cmd == "get":
                sys.stdout.write(text)
                return
            if ns.skills_cmd == "install":
                path = install_skill(ns.dir)
                emit({"ok": True, "path": str(path)})

        if ns.cmd == "plugins":
            if ns.plugins_cmd == "status":
                emit(plugin_status())
            if ns.plugins_cmd == "install":
                do_all = ns.all or not (ns.user_mcp or ns.claude or ns.skill)
                results: dict[str, str] = {}
                if do_all or ns.skill:
                    results["skill"] = str(install_skill(ns.dir))
                if do_all or ns.user_mcp:
                    results["user_mcp"] = str(install_user_mcp())
                if do_all or ns.claude:
                    results["claude"] = str(install_claude_mcp())
                emit({"ok": True, "installed": results, **plugin_status()})

        if ns.cmd == "doctor":
            report = run_doctor()
            emit(report, exit_code=0 if report["ok"] else 1)

    except SessionError as exc:
        fail(str(exc), code="session_error")
    except KeyboardInterrupt:
        fail("interrupted", code="interrupted", exit_code=130)


if __name__ == "__main__":
    main()
