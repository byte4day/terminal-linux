from __future__ import annotations

import json
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from . import actions, agent_tools, batch as batch_mod
from .errors import SessionError
from .session import get_running, list_sessions, open_app, start_session, stop_session


def resolve_cli() -> str:
    which = shutil.which("terminal-linux")
    if which:
        return str(Path(which).resolve())
    # Next to the interpreter as invoked (a venv's bin/), not its resolved target.
    local = Path(sys.executable).parent / "terminal-linux"
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


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def screenshot_bytes(state, **options: Any) -> bytes:
    """PNG bytes of the guest screen; the temporary file is removed."""
    path = actions.screenshot(state, **options)
    try:
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


AGENT_INSTRUCTIONS = """\
You control a separate Linux desktop (Xvfb + Openbox) for computer-use.
It has its own terminal window titled "agent-terminal" and usually Firefox.

Loop: status/up → screenshot → act → look again → repeat. stop when done.
Coordinates are pixels of the full screen (top-left origin), also in a
region or zoomed screenshot: read them off the grid labels (screenshot grid=true).
Pass screenshot=true on an action, or use batch, to get the new screen back in
the same call. Use wait_window after open, and wait_stable after page loads.
Prefer keyboard shortcuts, windows/focus and run_in_terminal over tiny click targets.
Never use the host desktop — only these tools.
"""


def build_server(name: str = "default"):
    """Create the FastMCP server with every tool registered (not yet running)."""
    try:
        from mcp.server.fastmcp import FastMCP, Image
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("mcp package missing; install with: uv sync") from exc

    server = FastMCP("terminal-linux", instructions=AGENT_INSTRUCTIONS)

    def session():
        return get_running(name)

    # Tools that can return an image carry no return annotation on purpose:
    # FastMCP would otherwise build a structured-output schema that an image
    # cannot satisfy.
    def reply(payload: dict[str, Any], want_shot: bool = False):
        """JSON text, plus the new screen as an image when asked for."""
        if not want_shot:
            return _json(payload)
        return [_json(payload), Image(data=screenshot_bytes(session()), format="png")]

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
        """Start the guest desktop (width x height pixels). Optionally open Firefox and agent-terminal.

        If the session already runs it is reused at its current size (see `reused`).
        """
        before = actions.status_payload(name)
        apps: list[list[str]] = []
        if not before["running"]:
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
                "reused": bool(before["running"]),
                "apps": state.apps,
                "hotkeys": agent_tools.hotkeys_help(),
            }
        )

    @server.tool()
    def stop(force: bool = False) -> str:
        """Stop the guest desktop session. force=true kills it at once and can lose guest work."""
        was_running = stop_session(name, force=force)
        return _json({"ok": True, "stopped": name, "force": force, "was_running": was_running})

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
        """Launch a command inside the guest (e.g. 'firefox', 'thunar ~/Downloads'). Shell quoting is honoured."""
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            raise SessionError(f"cannot parse command: {exc}", code="bad_args") from exc
        if not parts:
            raise SessionError("command is empty", code="bad_args")
        pid = open_app(name, parts)
        return _json({"ok": True, "pid": pid, "command": parts})

    @server.tool()
    def open_url(url: str) -> str:
        """Open a URL in the guest browser."""
        return _json(agent_tools.open_url(name, url))

    @server.tool()
    def windows() -> str:
        """List guest windows: id, class, title, x/y/width/height, center point, and which is active."""
        return _json({"ok": True, "windows": agent_tools.list_windows(name)})

    @server.tool()
    def active_window() -> str:
        """Return the focused guest window and geometry."""
        return _json({"ok": True, **agent_tools.active_window(name)})

    @server.tool()
    def focus(
        title: str | None = None,
        window_id: str | None = None,
        window_class: str | None = None,
    ) -> str:
        """Focus a guest window by title substring, class substring (e.g. 'firefox') or id."""
        return _json(agent_tools.focus_window(name, window_id=window_id, title=title, cls=window_class))

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
        """Write text to the guest clipboard (then paste with key ctrl+v)."""
        return _json(agent_tools.clipboard_set(name, text))

    @server.tool()
    def wait(seconds: float = 1.0) -> str:
        """Sleep up to 30s. Prefer wait_window or wait_stable when you know what you wait for."""
        return _json(agent_tools.wait(name, seconds))

    @server.tool()
    def wait_stable(timeout: float = 10.0, settle: float = 0.6) -> str:
        """Wait until the screen stops changing for `settle` seconds (or timeout). Check `stable`."""
        return _json(agent_tools.wait_stable(name, timeout=timeout, settle=settle))

    @server.tool()
    def wait_window(
        title: str | None = None,
        window_class: str | None = None,
        timeout: float = 10.0,
        gone: bool = False,
    ) -> str:
        """Wait for a window whose title/class contains the text to appear (gone=true: to close).

        Returns found/gone plus the window's geometry, or timeout=true. Use after `open`.
        """
        return _json(
            agent_tools.wait_window(name, title=title, cls=window_class, timeout=timeout, gone=gone)
        )

    @server.tool()
    def run_in_terminal(command: str, screenshot: bool = False):
        """Type a shell command into agent-terminal and press Enter. Output is on screen, not returned."""
        return reply(agent_tools.run_in_terminal(name, command), screenshot)

    @server.tool()
    def screenshot(
        grid: bool = False,
        region: list[int] | None = None,
        zoom: int = 1,
    ):
        """Capture the guest desktop as an image.

        grid=true overlays labelled coordinate lines for accurate clicks.
        region=[x, y, width, height] crops to that area; zoom (1-4) enlarges it
        to read small text. Grid labels and all tool coordinates stay in
        full-screen pixels.
        """
        data = screenshot_bytes(session(), grid=grid, region=region, zoom=zoom)
        return Image(data=data, format="png")

    @server.tool()
    def click(
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        screenshot: bool = False,
    ):
        """Click at pixel (x, y). button: left|middle|right. clicks: 1|2|3. screenshot=true returns the new screen."""
        state = session()
        actions.click(state, x, y, button=button, clicks=clicks)
        return reply({"ok": True, "x": x, "y": y, "button": button, "clicks": clicks}, screenshot)

    @server.tool()
    def move(x: int, y: int, screenshot: bool = False):
        """Move the guest pointer to (x, y), e.g. to hover."""
        state = session()
        actions.move(state, x, y)
        return reply({"ok": True, "x": x, "y": y}, screenshot)

    @server.tool()
    def drag(x1: int, y1: int, x2: int, y2: int, screenshot: bool = False):
        """Drag from (x1,y1) to (x2,y2) with the left button."""
        state = session()
        actions.drag(state, x1, y1, x2, y2)
        return reply({"ok": True, "from": [x1, y1], "to": [x2, y2]}, screenshot)

    @server.tool()
    def scroll(
        dy: int = 0,
        dx: int = 0,
        x: int | None = None,
        y: int | None = None,
        screenshot: bool = False,
    ):
        """Scroll at optional (x,y). Negative dy scrolls down; 120 is about three wheel notches."""
        state = session()
        actions.scroll(state, dy=dy, dx=dx, x=x, y=y)
        return reply({"ok": True, "dy": dy, "dx": dx, "x": x, "y": y}, screenshot)

    @server.tool(name="type")
    def type_tool(text: str, screenshot: bool = False):
        """Type literal Unicode text into the focused guest window (not via clipboard)."""
        state = session()
        actions.type_text(state, text)
        return reply({"ok": True, "chars": len(text)}, screenshot)

    @server.tool()
    def key(key: str, screenshot: bool = False):
        """Press a key or chord: return, tab, ctrl+c, alt+F4, super, ctrl++, cmd+space (cmd→ctrl).

        Several chords in order, separated by spaces: 'ctrl+a ctrl+c'.
        """
        state = session()
        actions.press_key(state, key)
        return reply({"ok": True, "key": key}, screenshot)

    @server.tool()
    def batch(steps: list[dict[str, Any]], screenshot: bool = True):
        """Run several steps in one call and get one screenshot of the result.

        Each step is {"action": NAME, ...args} with the same args as the single
        tools. Actions: click, move, drag, scroll, type, key, wait, wait_stable,
        wait_window, focus, open, open_url, run_in_terminal, clipboard_set,
        clipboard_get. Stops at the first failing step (see failed_step).
        Example: [{"action":"click","x":640,"y":60},{"action":"type","text":"hello"},
        {"action":"key","key":"return"},{"action":"wait_stable"}]
        """
        result = batch_mod.run_batch(name, steps)
        if not screenshot:
            return _json(result)
        try:
            return [_json(result), Image(data=screenshot_bytes(session()), format="png")]
        except SessionError:
            return _json(result)

    @server.resource("terminal-linux://hotkeys")
    def hotkeys_resource() -> str:
        return _json(agent_tools.hotkeys_help())

    @server.prompt("computer-use")
    def computer_use_prompt() -> str:
        return AGENT_INSTRUCTIONS + "\nHotkeys:\n" + _json(agent_tools.hotkeys_help())

    return server


def run_mcp(name: str = "default") -> None:
    build_server(name).run(transport="stdio")
