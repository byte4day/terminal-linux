from __future__ import annotations

import asyncio
import json
import tomllib
from pathlib import Path

import pytest

import terminal_linux
from terminal_linux import doctor, mcp_server, paths, plugins, viewer
from terminal_linux.errors import SessionError

ROOT = Path(__file__).resolve().parents[1]


def test_versions_agree():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert terminal_linux.__version__ == pyproject == plugin
    assert f"## {pyproject} " in (ROOT / "CHANGELOG.md").read_text()


def test_runtime_resources_ship_inside_the_package():
    # Regression: these lived at the repo root, so a non-editable install
    # (`uv tool install .`) had no openbox, no agent shell and no skill.
    assert (paths.VENDOR_OPENBOX / "usr" / "bin" / "openbox").is_file()
    assert (paths.ASSETS_DIR / "agent-shell.sh").is_file()
    assert (paths.ASSETS_DIR / "alacritty-agent.toml").is_file()
    assert paths.PACKAGE_DIR in paths.VENDOR_OPENBOX.parents


def test_bundled_skill_and_agent_are_the_repo_files():
    assert plugins.skill_text() == (ROOT / "skills" / "terminal-linux" / "SKILL.md").read_text()
    assert plugins.agent_text() == (ROOT / "agents" / "claude" / "terminal-linux.md").read_text()


def _frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n")
    block = text.split("---\n", 2)[1]
    return {
        line.split(":", 1)[0]: line.split(":", 1)[1].strip()
        for line in block.splitlines()
        if ":" in line and not line.startswith((" ", "-"))
    }


def test_skill_and_agent_frontmatter():
    skill = _frontmatter(plugins.skill_text())
    assert skill["name"] == "terminal-linux" and 40 < len(skill["description"]) <= 1024
    agent = _frontmatter(plugins.agent_text())
    assert agent["name"] == "terminal-linux" and agent["description"]
    assert "/absolute/path" not in plugins.skill_text()


def test_skill_names_only_real_tools():
    tools = {t.name for t in asyncio.run(mcp_server.build_server("t").list_tools())}
    text = plugins.skill_text()
    section = text.split("## MCP tools", 1)[1].split("##", 1)[0]
    named = {word.strip("`") for word in section.split() if word.startswith("`")}
    assert named and named <= tools, named - tools
    assert tools <= named, f"tools missing from the skill: {tools - named}"


def test_plugin_manifest_points_at_existing_files():
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    for rel in manifest["agents"]:
        assert rel.startswith("./") and (ROOT / rel).is_file()
    assert (ROOT / manifest["skills"] / "terminal-linux" / "SKILL.md").is_file()


def test_install_skill_and_agent_are_idempotent(tmp_path):
    skill = plugins.install_skill(tmp_path / "skills")
    agent = plugins.install_agent(tmp_path / "agents")
    assert skill == tmp_path / "skills" / "terminal-linux" / "SKILL.md"
    assert agent == tmp_path / "agents" / "terminal-linux.md"
    before = (skill.stat().st_mtime_ns, agent.stat().st_mtime_ns)
    plugins.install_skill(tmp_path / "skills")
    plugins.install_agent(tmp_path / "agents")
    assert (skill.stat().st_mtime_ns, agent.stat().st_mtime_ns) == before
    assert skill.read_text() == plugins.skill_text()


def test_mcp_config_merge_keeps_other_servers(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    plugins.install_user_mcp(cfg)
    plugins.install_user_mcp(cfg)  # twice: same result
    data = json.loads(cfg.read_text())
    assert data["theme"] == "dark" and set(data["mcpServers"]) == {"other", "terminal-linux"}
    assert data["mcpServers"]["terminal-linux"]["args"] == ["mcp", "default"]


def test_mcp_config_merge_refuses_unparseable_file(tmp_path):
    # Regression: a config that failed to parse was replaced, deleting the
    # user's other MCP servers.
    cfg = tmp_path / "mcp.json"
    original = '{"mcpServers": {"other": {}}, // a comment\n}'
    cfg.write_text(original)
    with pytest.raises(SessionError) as err:
        plugins.install_user_mcp(cfg)
    assert err.value.code == "bad_config"
    assert cfg.read_text() == original


def test_mcp_tools_and_schemas():
    tools = {t.name: t for t in asyncio.run(mcp_server.build_server("t").list_tools())}
    for name in ("batch", "wait_window", "wait_stable", "windows", "focus", "screenshot", "clipboard_set"):
        assert name in tools
    shot = tools["screenshot"].inputSchema["properties"]
    assert {"grid", "region", "zoom"} <= set(shot)
    assert tools["batch"].inputSchema["required"] == ["steps"]
    assert {"title", "window_class", "timeout", "gone"} <= set(tools["wait_window"].inputSchema["properties"])
    for name in ("click", "type", "key", "scroll", "drag", "move", "run_in_terminal"):
        assert "screenshot" in tools[name].inputSchema["properties"], name
    assert all(t.description for t in tools.values())


def test_mcp_tool_errors_are_reported_not_raised():
    server = mcp_server.build_server("t")  # session 't' is not running

    async def call():
        try:
            result = await server.call_tool("click", {"x": 1, "y": 1})
        except Exception as exc:  # FastMCP raises ToolError, which the transport reports as isError
            return str(exc)
        return str(result)

    assert "not running" in asyncio.run(call())


def test_mcp_status_works_without_a_session():
    server = mcp_server.build_server("t")
    result = asyncio.run(server.call_tool("status", {}))
    assert '"running": false' in str(result)


def test_doctor_marks_required_checks(monkeypatch):
    report = doctor.run_doctor()
    required = {c["name"] for c in report["checks"] if c["required"]}
    assert required == {"Xvfb", "xdotool", "import", "openbox"}
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None if name == "xclip" else f"/usr/bin/{name}")
    report = doctor.run_doctor()
    xclip = next(c for c in report["checks"] if c["name"] == "xclip")
    assert xclip["ok"] is False and xclip["required"] is False
    assert report["ok"] is True  # an optional tool does not fail the check
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None if name == "Xvfb" else f"/usr/bin/{name}")
    report = doctor.run_doctor()
    assert report["ok"] is False and report["missing"] == ["Xvfb"]


def test_viewer_input_errors_do_not_escape(fake_state, monkeypatch):
    # Regression: a key the guest rejects ended the live preview with a traceback.
    shown: list[str] = []
    monkeypatch.setattr(viewer, "_status_line", shown.append)

    def boom(state, spec):
        raise SessionError("No such key name")

    monkeypatch.setattr(viewer.actions, "press_key", boom)
    assert viewer.guest.press_key(fake_state, "alt+§") is None
    assert shown and "No such key name" in shown[0]
    assert viewer._alt_chord(32) == "alt+space" and viewer._alt_chord(ord("x")) == "alt+x"
