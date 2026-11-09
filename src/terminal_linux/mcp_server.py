from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from . import actions, agent_tools
from .session import SessionError, get_running, list_sessions, open_app, start_session, stop_session


def resolve_cli() -> str:
    which = shutil.which("terminal-linux")
    if which:
        return str(Path(which).resolve())
    local = Path(sys.executable).resolve().parent / "terminal-linux"
    if local.exists():
        return str(local)
    return "terminal-linux"


def mcp_config_snippet(name: str = "default", *, client: str = "claude") -> dict[str, Any]:
    exe = resolve_cli()
    server = {"command": exe, "args": ["mcp", name]}
    if client == "vscode":
        return {"servers": {"terminal-linux": {"type": "stdio", **server}}}
    # claude / generic share the mcpServers shape
    return {"mcpServers": {"terminal-linux": server}}


def _maybe_shot(state, want: bool) -> dict[str, Any]:
    if not want:
        return {}
    path = actions.screenshot(state)
    return {"screenshot": str(path)}


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


AGENT_INSTRUCTIONS = """\
You control a separate Linux desktop (Xvfb + Openbox) for computer-use.
It has its own terminal window titled "agent-terminal" and usually Firefox.

Loop: status/up → screenshot → act → screenshot/wait_stable → repeat.
Coordinates are pixels from the latest screenshot (top-left origin).
Prefer keyboard shortcuts and run_in_terminal over tiny click targets.
Never use the host desktop — only these tools.
"""


def run_mcp(name: str = "default") -> None:
    try:
        from mcp.server.fastmcp import FastMCP, Image
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("mcp package missing; install with: uv sync") from exc

    server = FastMCP("terminal-linux", instructions=AGENT_INSTRUCTIONS)

    def session():
        return get_running(name)

    @server.tool()
    def status() -> str:
        """Report whether the Linux desktop session is running and ready."""
        return _json(actions.status_payload(name))

    @server.tool()
    def up(
        width: int = 1280,
        height: int = 800,
        with_browser: bool = True,
        with_terminal: bool = True,
    ) -> str:
        """Start the guest desktop. Optionally open Firefox and agent-terminal."""
        apps: list[list[str]] = []
        if with_terminal:
            try:
                apps.append(agent_tools.pick_guest_terminal())
            except SessionError:
                pass
        if with_browser and shutil.which("firefox"):
            apps.append(["firefox"])
        state = start_session(name, width=width, height=height, apps=apps)
        return _json(
            {
                "ok": True,
                "name": state.name,
                "display": state.display_name,
                "width": state.width,
                "height": state.height,
                "apps": state.apps,
                "hotkeys": agent_tools.hotkeys_help(),
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

    @server.tool()
    def workspace() -> str:
        """Ensure agent-terminal + Firefox are open; return window list."""
        return _json(agent_tools.ensure_agent_workspace(name))

    @server.tool(name="open")
    def open_tool(command: str) -> str:
        """Launch a command inside the guest (e.g. 'firefox', 'alacritty')."""
        parts = command.strip().split()
        if not parts:
            raise SessionError("command is empty")
        pid = open_app(name, parts)
        return _json({"ok": True, "pid": pid, "command": parts})

    @server.tool()
    def open_url(url: str) -> str:
        """Open a URL in the guest browser."""
        return _json(agent_tools.open_url(name, url))

    @server.tool()
    def windows() -> str:
        """List guest windows (id, class, title)."""
        return _json({"ok": True, "windows": agent_tools.list_windows(name)})

    @server.tool()
    def active_window() -> str:
        """Return the focused guest window and geometry."""
        return _json({"ok": True, **agent_tools.active_window(name)})

    @server.tool()
    def focus(title: str | None = None, window_id: str | None = None) -> str:
        """Focus a guest window by title substring or id."""
        return _json(agent_tools.focus_window(name, window_id=window_id, title=title))

    @server.tool()
    def cursor() -> str:
        """Current guest pointer x/y."""
        return _json(agent_tools.cursor_position(name))

    @server.tool()
    def clipboard_get() -> str:
        """Read the guest clipboard text."""
        return _json(agent_tools.clipboard_get(name))

    @server.tool()
    def clipboard_set(text: str) -> str:
        """Write text to the guest clipboard."""
        return _json(agent_tools.clipboard_set(name, text))

    @server.tool()
    def wait(seconds: float = 1.0) -> str:
        """Sleep up to 30s (UI settle / page load)."""
        return _json(agent_tools.wait(name, seconds))

    @server.tool()
    def wait_stable(timeout: float = 10.0, settle: float = 0.6) -> str:
        """Wait until the screen stops changing (or timeout)."""
        return _json(agent_tools.wait_stable(name, timeout=timeout, settle=settle))

    @server.tool()
    def run_in_terminal(command: str) -> str:
        """Type a shell command into agent-terminal and press Enter."""
        return _json(agent_tools.run_in_terminal(name, command))

    @server.tool()
    def screenshot() -> Image:
        """Capture the guest desktop. Coordinates for other tools match this image."""
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
        """Scroll at optional (x,y). Negative dy scrolls down."""
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
        """Press a key/chord: return, tab, ctrl+c, alt+F4, cmd+space (cmd→ctrl)."""
        state = session()
        actions.press_key(state, key)
        payload = {"ok": True, "key": key}
        payload.update(_maybe_shot(state, screenshot))
        return _json(payload)

    @server.resource("terminal-linux://hotkeys")
    def hotkeys_resource() -> str:
        return _json(agent_tools.hotkeys_help())

    @server.prompt("computer-use")
    def computer_use_prompt() -> str:
        return AGENT_INSTRUCTIONS + "\nHotkeys:\n" + _json(agent_tools.hotkeys_help())

    server.run(transport="stdio")
