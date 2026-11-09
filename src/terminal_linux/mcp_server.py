from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from . import actions
from .session import SessionError, get_running, list_sessions, open_app, start_session, stop_session


def resolve_cli() -> str:
    """Prefer an absolute on-PATH binary so MCP clients don't depend on cwd."""
    which = shutil.which("terminal-linux")
    if which:
        return str(Path(which).resolve())
    # uv / editable install fallback
    local = Path(sys.executable).resolve().parent / "terminal-linux"
    if local.exists():
        return str(local)
    return "terminal-linux"


def mcp_config_snippet(name: str = "default", *, client: str = "claude") -> dict[str, Any]:
    exe = resolve_cli()
    server = {
        "command": exe,
        "args": ["mcp", name],
    }
    if client == "vscode":
        return {
            "servers": {
                "terminal-linux": {
                    "type": "stdio",
                    **server,
                }
            }
        }
    return {"mcpServers": {"terminal-linux": server}}


def _maybe_shot(state, want: bool) -> dict[str, Any]:
    if not want:
        return {}
    path = actions.screenshot(state)
    return {"screenshot": str(path)}


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def run_mcp(name: str = "default") -> None:
    """stdio MCP server for computer-use tools."""
    try:
        from mcp.server.fastmcp import FastMCP, Image
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("mcp package missing; install with: uv sync") from exc

    server = FastMCP(
        "terminal-linux",
        instructions=(
            "Control a separate Linux desktop (Xvfb) for computer-use. "
            "Call status first; if not running, call up. "
            "Always screenshot before acting. Coordinates are pixels from the latest screenshot "
            "(top-left origin). Prefer keyboard shortcuts over tiny click targets. "
            "Never fall back to the host desktop."
        ),
    )

    def session():
        return get_running(name)

    @server.tool()
    def status() -> str:
        """Report whether the Linux desktop session is running and ready."""
        return _json(actions.status_payload(name))

    @server.tool()
    def up(width: int = 1280, height: int = 800, open_app_cmd: str | None = None) -> str:
        """Start the guest desktop session if needed. Optionally launch an app (e.g. 'firefox')."""
        apps = [open_app_cmd.split()] if open_app_cmd else None
        state = start_session(name, width=width, height=height, apps=apps)
        return _json(
            {
                "ok": True,
                "name": state.name,
                "display": state.display_name,
                "width": state.width,
                "height": state.height,
                "xvfb_pid": state.xvfb_pid,
                "wm_pid": state.wm_pid,
                "apps": state.apps,
            }
        )

    @server.tool()
    def stop(force: bool = False) -> str:
        """Stop the guest desktop session."""
        stop_session(name, force=force)
        return _json({"ok": True, "stopped": name, "force": force})

    @server.tool()
    def ls() -> str:
        """List known terminal-linux sessions."""
        return _json({"ok": True, "sessions": list_sessions()})

    @server.tool(name="open")
    def open_tool(command: str) -> str:
        """Launch a command inside the guest (e.g. 'firefox', 'thunar', 'xterm')."""
        parts = command.strip().split()
        if not parts:
            raise SessionError("command is empty")
        pid = open_app(name, parts)
        return _json({"ok": True, "pid": pid, "command": parts})

    @server.tool()
    def screenshot() -> Image:
        """Capture the guest desktop. Coordinates for other tools match this image (top-left origin)."""
        state = session()
        path = actions.screenshot(state)
        return Image(path=path, format="png")

    @server.tool()
    def click(
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        screenshot: bool = False,
    ) -> str:
        """Click at pixel (x, y). button: left|middle|right. clicks: 1|2|3."""
        state = session()
        actions.click(state, x, y, button=button, clicks=clicks)
        payload = {"ok": True, "x": x, "y": y, "button": button, "clicks": clicks}
        payload.update(_maybe_shot(state, screenshot))
        return _json(payload)

    @server.tool()
    def move(x: int, y: int, screenshot: bool = False) -> str:
        """Move the guest pointer to (x, y)."""
        state = session()
        actions.move(state, x, y)
        payload = {"ok": True, "x": x, "y": y}
        payload.update(_maybe_shot(state, screenshot))
        return _json(payload)

    @server.tool()
    def drag(x1: int, y1: int, x2: int, y2: int, screenshot: bool = False) -> str:
        """Drag from (x1,y1) to (x2,y2) with the left button."""
        state = session()
        actions.drag(state, x1, y1, x2, y2)
        payload = {"ok": True, "from": [x1, y1], "to": [x2, y2]}
        payload.update(_maybe_shot(state, screenshot))
        return _json(payload)

    @server.tool()
    def scroll(
        dy: int = 0,
        dx: int = 0,
        x: int | None = None,
        y: int | None = None,
        screenshot: bool = False,
    ) -> str:
        """Scroll at optional (x,y). Negative dy scrolls down (same as terminal-mac)."""
        state = session()
        actions.scroll(state, dy=dy, dx=dx, x=x, y=y)
        payload = {"ok": True, "dy": dy, "dx": dx, "x": x, "y": y}
        payload.update(_maybe_shot(state, screenshot))
        return _json(payload)

    @server.tool(name="type")
    def type_tool(text: str, screenshot: bool = False) -> str:
        """Type literal Unicode text into the guest (not via clipboard)."""
        state = session()
        actions.type_text(state, text)
        payload = {"ok": True, "text": text}
        payload.update(_maybe_shot(state, screenshot))
        return _json(payload)

    @server.tool()
    def key(key: str, screenshot: bool = False) -> str:
        """Press a key or chord, e.g. return, tab, ctrl+c, alt+F4, cmd+space (cmd→ctrl)."""
        state = session()
        actions.press_key(state, key)
        payload = {"ok": True, "key": key}
        payload.update(_maybe_shot(state, screenshot))
        return _json(payload)

    server.run(transport="stdio")
