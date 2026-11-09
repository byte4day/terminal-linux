from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .mcp_server import mcp_config_snippet, resolve_cli
from .paths import PACKAGE_ROOT


def _skill_source() -> Path:
    return PACKAGE_ROOT / "skills" / "terminal-linux" / "SKILL.md"


def install_skill(target_dir: Path | None = None) -> Path:
    src = _skill_source()
    if not src.exists():
        raise FileNotFoundError(f"skill missing: {src}")
    root = target_dir or (Path.home() / ".claude" / "skills")
    dest_dir = root / "terminal-linux"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "SKILL.md"
    dest.write_text(src.read_text())
    return dest


def install_user_mcp(target: Path | None = None) -> Path:
    """Write/merge terminal-linux into the user MCP config under XDG."""
    path = target or (Path.home() / ".config" / "terminal-linux" / "mcp.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except json.JSONDecodeError:
            existing = {}
    servers = existing.setdefault("mcpServers", {})
    servers["terminal-linux"] = mcp_config_snippet()["mcpServers"]["terminal-linux"]
    path.write_text(json.dumps(existing, indent=2) + "\n")
    return path


def install_claude_mcp(target: Path | None = None) -> Path:
    """Write/merge into Claude Desktop-style config if present, else XDG config."""
    candidates = [
        target,
        Path.home() / ".config" / "claude" / "claude_desktop_config.json",
        Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
    ]
    path = next((p for p in candidates if p is not None), None)
    assert path is not None
    if target is None:
        desktop = next((p for p in candidates[1:] if p.exists()), None)
        path = desktop or (Path.home() / ".config" / "terminal-linux" / "mcp.json")

    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except json.JSONDecodeError:
            existing = {}
    servers = existing.setdefault("mcpServers", {})
    servers["terminal-linux"] = mcp_config_snippet()["mcpServers"]["terminal-linux"]
    path.write_text(json.dumps(existing, indent=2) + "\n")
    return path


def plugin_status() -> dict[str, Any]:
    cli = resolve_cli()
    return {
        "ok": True,
        "cli": cli,
        "cli_on_path": bool(shutil.which("terminal-linux")),
        "skill": str(_skill_source()) if _skill_source().exists() else None,
        "claude_plugin": str(PACKAGE_ROOT / ".claude-plugin" / "plugin.json"),
        "marketplace": str(PACKAGE_ROOT / ".claude-plugin" / "marketplace.json"),
        "repo_mcp": str(PACKAGE_ROOT / ".mcp.json"),
        "install_hints": {
            "claude_code_plugin": "claude plugin marketplace add byte4day/terminal-linux then /plugin install terminal-linux@terminal-linux",
            "claude_mcp": f"claude mcp add terminal-linux -- {cli} mcp default",
            "user_mcp": "terminal-linux plugins install --user-mcp",
            "skill": "terminal-linux skills install",
        },
    }


def write_client_configs() -> dict[str, str]:
    """Refresh checked-in client config snippets."""
    out: dict[str, str] = {}
    mapping = {
        PACKAGE_ROOT / ".mcp.json": "claude",
        PACKAGE_ROOT / "mcp" / "claude.json": "claude",
        PACKAGE_ROOT / "mcp" / "generic.json": "claude",
        PACKAGE_ROOT / "mcp" / "vscode.json": "vscode",
    }
    for path, client in mapping.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = mcp_config_snippet(client=client)
        if client != "vscode":
            payload["mcpServers"]["terminal-linux"]["command"] = "terminal-linux"
        else:
            payload["servers"]["terminal-linux"]["command"] = "terminal-linux"
        path.write_text(json.dumps(payload, indent=2) + "\n")
        out[str(path)] = "written"
    plugin = PACKAGE_ROOT / ".claude-plugin" / "plugin.json"
    if plugin.exists():
        data = json.loads(plugin.read_text())
        data.setdefault("mcpServers", {})["terminal-linux"] = {
            "command": "terminal-linux",
            "args": ["mcp", "default"],
        }
        plugin.write_text(json.dumps(data, indent=2) + "\n")
        out[str(plugin)] = "written"
    return out
