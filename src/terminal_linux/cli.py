from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, actions
from .doctor import run_doctor
from .jsonutil import emit, fail
from .mcp_server import mcp_config_snippet, run_mcp
from .plugins import install_claude_mcp, install_cursor_mcp, install_skill, plugin_status
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

    up = sub.add_parser("up", help="create/start a desktop session and open the viewer")
    up.add_argument("name", nargs="?", default="default")
    up.add_argument("--width", type=int, default=1280)
    up.add_argument("--height", type=int, default=800)
    up.add_argument("--no-view", action="store_true", help="start session and print JSON only")
    up.add_argument("--detach", action="store_true", help="alias of --no-view")
    up.add_argument("--open", action="append", default=[], metavar="APP", help="launch APP inside the session (repeatable)")

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

    view = sub.add_parser("view", help="stream the guest desktop into the terminal")
    view.add_argument("name", nargs="?", default="default")
    view.add_argument("--fps", type=float, default=8.0)

    open_p = sub.add_parser("open", help="launch a command inside the session")
    open_p.add_argument("name", nargs="?", default="default")
    open_p.add_argument("command", nargs=argparse.REMAINDER, help="command after --")

    action = sub.add_parser("action", help="computer-use actions (JSON)")
    action.add_argument("name", nargs="?", default="default")
    action.add_argument(
        "verb",
        choices=["status", "screenshot", "click", "move", "drag", "type", "key", "scroll"],
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
    action.add_argument("--screenshot", action="store_true", help="return a fresh screenshot path")

    mcp = sub.add_parser("mcp", help="run MCP server (stdio) or print client config")
    mcp.add_argument("name", nargs="?", default="default")
    mcp.add_argument("--config", action="store_true", help="print MCP client config JSON and exit")
    mcp.add_argument(
        "--client",
        default="claude",
        choices=["claude", "cursor", "vscode"],
        help="config shape for --config (default: claude)",
    )

    skills = sub.add_parser("skills", help="agent skill helpers")
    skills_sub = skills.add_subparsers(dest="skills_cmd", required=True)
    skills_get = skills_sub.add_parser("get", help="print the agent skill markdown")
    skills_get.add_argument("--dir", type=Path, default=None)
    skills_install = skills_sub.add_parser("install", help="install skill into a skills directory")
    skills_install.add_argument("--dir", type=Path, default=None)

    plugins = sub.add_parser("plugins", help="install Claude/Cursor MCP + skill plugin pieces")
    plugins_sub = plugins.add_subparsers(dest="plugins_cmd", required=True)
    plugins_sub.add_parser("status", help="show plugin / MCP install status")
    plug_install = plugins_sub.add_parser("install", help="install skill + MCP configs")
    plug_install.add_argument("--cursor", action="store_true", help="merge into ~/.cursor/mcp.json")
    plug_install.add_argument("--claude", action="store_true", help="merge into Claude MCP config")
    plug_install.add_argument("--skill", action="store_true", help="install agent skill")
    plug_install.add_argument("--all", action="store_true", help="install skill + cursor + claude")
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
            if ns.cmd == "start" or getattr(ns, "no_view", False) or getattr(ns, "detach", False):
                emit(payload)
            print(json.dumps(payload, indent=2), file=sys.stderr)
            raise SystemExit(run_viewer(ns.name))

        if ns.cmd in {"stop", "down"}:
            stop_session(ns.name, force=ns.force)
            emit({"ok": True, "stopped": ns.name, "force": ns.force})

        if ns.cmd == "status":
            emit(actions.status_payload(ns.name))

        if ns.cmd == "ls":
            emit({"ok": True, "sessions": list_sessions()})

        if ns.cmd == "view":
            raise SystemExit(run_viewer(ns.name, fps=ns.fps))

        if ns.cmd == "open":
            cmd = list(ns.command)
            if cmd and cmd[0] == "--":
                cmd = cmd[1:]
            if not cmd:
                fail("usage: terminal-linux open [NAME] -- COMMAND...")
            pid = open_app(ns.name, cmd)
            emit({"ok": True, "pid": pid, "command": cmd})

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
                do_all = ns.all or not (ns.cursor or ns.claude or ns.skill)
                results: dict[str, str] = {}
                if do_all or ns.skill:
                    results["skill"] = str(install_skill(ns.dir))
                if do_all or ns.cursor:
                    results["cursor"] = str(install_cursor_mcp())
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
