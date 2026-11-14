from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .errors import SessionError
from .mcp_server import mcp_config_snippet, resolve_cli
from .paths import BUNDLE_DIR, PACKAGE_DIR

# The skill and the agent ship inside the package (bundle/ holds links to the
# repo's skills/ and agents/ files, which a wheel build stores as real files),
# so `skills install` works from an installed CLI as well as from a checkout.
SKILL_SOURCE = BUNDLE_DIR / "SKILL.md"
AGENT_SOURCE = BUNDLE_DIR / "agent.md"


def repo_root() -> Path | None:
    """The source checkout, when running from one (editable install or `uv run`)."""
    root = PACKAGE_DIR.parents[1]
    return root if (root / ".claude-plugin" / "plugin.json").exists() else None


def _read(source: Path, what: str) -> str:
    try:
        return source.read_text()
    except OSError:
        raise SessionError(f"{what} is missing from this install: {source}", code="not_found") from None


def skill_text() -> str:
    return _read(SKILL_SOURCE, "skill")


def agent_text() -> str:
    return _read(AGENT_SOURCE, "agent")


def _install(text: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.read_text() != text:
        dest.write_text(text)
    return dest


def install_skill(target_dir: Path | None = None) -> Path:
    root = Path(target_dir).expanduser() if target_dir else Path.home() / ".claude" / "skills"
    return _install(skill_text(), root / "terminal-linux" / "SKILL.md")


def install_agent(target_dir: Path | None = None) -> Path:
    """Install the Claude Code subagent (default: ~/.claude/agents/terminal-linux.md)."""
    root = Path(target_dir).expanduser() if target_dir else Path.home() / ".claude" / "agents"
    return _install(agent_text(), root / "terminal-linux.md")


def _merge_mcp_config(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: Any = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except json.JSONDecodeError:
            # Never overwrite a config we cannot parse: the user's other servers live there.
            raise SessionError(f"{path} is not valid JSON; fix or move it, then retry", code="bad_config") from None
    if not isinstance(existing, dict):
        raise SessionError(f"{path} does not hold a JSON object", code="bad_config")
    servers = existing.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise SessionError(f"{path}: mcpServers is not an object", code="bad_config")
    servers["terminal-linux"] = mcp_config_snippet()["mcpServers"]["terminal-linux"]
    path.write_text(json.dumps(existing, indent=2) + "\n")
    return path


def install_user_mcp(target: Path | None = None) -> Path:
    """Write/merge terminal-linux into the user MCP config under XDG."""
    return _merge_mcp_config(target or (Path.home() / ".config" / "terminal-linux" / "mcp.json"))


def install_claude_mcp(target: Path | None = None) -> Path:
    """Merge into a Claude Desktop config when one exists, else the XDG config."""
    if target is None:
        candidates = [
            Path.home() / ".config" / "claude" / "claude_desktop_config.json",
            Path.home() / ".config" / "Claude" / "claude_desktop_config.json",
            Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
        ]
        target = next((p for p in candidates if p.exists()), None)
        if target is None:
            target = Path.home() / ".config" / "terminal-linux" / "mcp.json"
    return _merge_mcp_config(target)


def _installed(dest: Path, text: str | None) -> dict[str, Any]:
    exists = dest.exists()
    return {
        "path": str(dest),
        "installed": exists,
        "current": bool(exists and text is not None and dest.read_text() == text),
    }


def plugin_status() -> dict[str, Any]:
    cli = resolve_cli()
    root = repo_root()
    skill = SKILL_SOURCE.read_text() if SKILL_SOURCE.exists() else None
    agent = AGENT_SOURCE.read_text() if AGENT_SOURCE.exists() else None
    status: dict[str, Any] = {
        "ok": True,
        "cli": cli,
        "cli_on_path": bool(shutil.which("terminal-linux")),
        "skill": _installed(Path.home() / ".claude" / "skills" / "terminal-linux" / "SKILL.md", skill),
        "agent": _installed(Path.home() / ".claude" / "agents" / "terminal-linux.md", agent),
        "install_hints": {
            "claude_code_plugin": "/plugin marketplace add byte4day/terminal-linux then /plugin install terminal-linux@terminal-linux",
            "claude_mcp": f"claude mcp add --scope user terminal-linux -- {cli} mcp default",
            "user_mcp": "terminal-linux plugins install --user-mcp",
            "skill": "terminal-linux plugins install --skill",
            "agent": "terminal-linux plugins install --agent",
        },
    }
    if root is not None:
        status["claude_plugin"] = str(root / ".claude-plugin" / "plugin.json")
        status["marketplace"] = str(root / ".claude-plugin" / "marketplace.json")
        status["repo_mcp"] = str(root / ".mcp.json")
    return status


def write_client_configs() -> dict[str, str]:
    """Refresh the checked-in client config snippets (source checkout only)."""
    root = repo_root()
    if root is None:
        raise SessionError("write_client_configs needs a source checkout", code="not_found")
    out: dict[str, str] = {}
    mapping = {
        root / ".mcp.json": "claude",
        root / "mcp" / "claude.json": "claude",
        root / "mcp" / "generic.json": "claude",
        root / "mcp" / "vscode.json": "vscode",
    }
    for path, client in mapping.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = mcp_config_snippet(client=client)
        key = "servers" if client == "vscode" else "mcpServers"
        payload[key]["terminal-linux"]["command"] = "terminal-linux"
        path.write_text(json.dumps(payload, indent=2) + "\n")
        out[str(path)] = "written"
    plugin = root / ".claude-plugin" / "plugin.json"
    if plugin.exists():
        data = json.loads(plugin.read_text())
        data.setdefault("mcpServers", {})["terminal-linux"] = {
            "command": "terminal-linux",
            "args": ["mcp", "default"],
        }
        plugin.write_text(json.dumps(data, indent=2) + "\n")
        out[str(plugin)] = "written"
    return out
