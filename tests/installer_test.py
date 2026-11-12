"""Installer test in a fake home (real configs are never touched).
Usage: uv run python tests/installer_test.py"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "music-studio-mcp-for-ace-step"
uv = shutil.which("uv")

with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    appdata, local = home / "AppData/Roaming", home / "AppData/Local"
    (appdata / "Claude").mkdir(parents=True)
    (appdata / "Claude/claude_desktop_config.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    (local / "Packages/Claude_test/LocalCache/Roaming/Claude").mkdir(parents=True)
    (home / ".claude.json").write_text(json.dumps({"numStartups": 3}))
    (home / ".codex").mkdir()
    (home / ".codex/config.toml").write_text('model = "gpt-5"\n\n[mcp_servers.other]\ncommand = "x"\n\n'
                                              '[mcp_servers.other.env]\nA = "1"\n')
    (appdata / "Code/User/globalStorage/saoudrizwan.claude-dev").mkdir(parents=True)
    (appdata / "Code/User/globalStorage/rooveterinaryinc.roo-cline").mkdir(parents=True)
    (appdata / "Zed").mkdir(parents=True)
    (appdata / "Zed/settings.json").write_text("{\n  // comment\n}")  # JSONC: must be left alone
    for d in (".gemini", ".qwen", ".copilot", ".cursor", ".kiro", ".lmstudio", ".config/opencode", ".continue"):
        (home / d).mkdir(parents=True)
    # an old entry of ours sits between two other servers, with its own args list (the case that once left
    # our args attached to the previous server)
    continue_before = (
        "name: Test\nmodels:\n  - name: m\n    provider: openai\n\nmcpServers:\n  - name: Other\n    command: npx\n"
        "    args:\n      - -y\n      - other-server\n"
        f"  - name: {NAME}\n    type: stdio\n    command: 'C:\\old\\uv.exe'\n    args:\n      - 'run'\n"
        "      - '--script'\n      - 'C:\\old\\music_studio_mcp.py'\n"
        "  - name: Third\n    command: third\n\ncontext: []\n")
    (home / ".continue/config.yaml").write_text(continue_before)
    (home / ".local/bin").mkdir(parents=True)
    shutil.copy2(uv, home / ".local/bin/uv.exe")
    env = dict(os.environ, USERPROFILE=str(home), HOME=str(home), APPDATA=str(appdata), LOCALAPPDATA=str(local),
               PATH=r"C:\Windows\System32", UV_CACHE_DIR=str(Path(os.environ["LOCALAPPDATA"]) / "uv" / "cache"))

    def run(*a):
        r = subprocess.run([sys.executable, str(ROOT / "mcp/install.py"), *a], env=env, capture_output=True,
                           text=True, encoding="utf-8")
        print(r.stdout, r.stderr)
        return r

    run("--all")
    j = lambda p: json.loads(Path(p).read_text())
    assert set(j(appdata / "Claude/claude_desktop_config.json")["mcpServers"]) == {"other", NAME}
    assert j(appdata / "Claude/claude_desktop_config.json")["mcpServers"][NAME]["args"][-1].endswith("music_studio_mcp.py")
    assert NAME in j(local / "Packages/Claude_test/LocalCache/Roaming/Claude/claude_desktop_config.json")["mcpServers"]
    assert j(home / ".claude.json")["numStartups"] == 3 and NAME in j(home / ".claude.json")["mcpServers"]
    t = tomllib.loads((home / ".codex/config.toml").read_text())
    assert t["model"] == "gpt-5" and set(t["mcp_servers"]) == {"other", NAME} and t["mcp_servers"]["other"]["env"] == {"A": "1"}
    for f in (".gemini/settings.json", ".qwen/settings.json", ".cursor/mcp.json", ".kiro/settings/mcp.json", ".lmstudio/mcp.json"):
        assert NAME in j(home / f)["mcpServers"], f
    assert j(home / ".copilot/mcp-config.json")["mcpServers"][NAME]["type"] == "local"
    assert j(home / ".config/opencode/opencode.json")["mcp"][NAME]["command"][0].endswith("uv.exe")
    assert j(appdata / "Code/User/mcp.json")["servers"][NAME]["type"] == "stdio"
    assert NAME in j(appdata / "Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json")["mcpServers"]
    assert NAME in j(appdata / "Code/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json")["mcpServers"]
    assert (appdata / "Zed/settings.json").read_text() == "{\n  // comment\n}"
    y = (home / ".continue/config.yaml").read_text()
    assert y.count(f"- name: {NAME}") == 1 and "C:\\old\\" not in y, y  # old entry fully replaced
    assert "    args:\n      - -y\n      - other-server\n  - name: Third" in y, y  # neighbours untouched
    assert y.index("  - name: Other") < y.index(f"  - name: {NAME}") < y.index("context: []"), y
    assert list((appdata / "Claude").glob("*.bak-*")), "backup missing"

    run("--all")  # idempotent: still one entry everywhere
    assert tomllib.loads((home / ".codex/config.toml").read_text())["mcp_servers"].keys() == {"other", NAME}
    assert (home / ".continue/config.yaml").read_text().count(NAME) == 1

    run("--all", "--uninstall")
    assert set(j(appdata / "Claude/claude_desktop_config.json")["mcpServers"]) == {"other"}
    t = tomllib.loads((home / ".codex/config.toml").read_text())
    assert set(t["mcp_servers"]) == {"other"} and t["model"] == "gpt-5", t
    assert NAME not in j(home / ".claude.json").get("mcpServers", {})
    y = (home / ".continue/config.yaml").read_text()
    assert NAME not in y and "music_studio_mcp.py" not in y and "'run'" not in y, y  # nothing of ours is left
    assert "    args:\n      - -y\n      - other-server\n  - name: Third\n    command: third" in y, y
    assert "context: []" in y, y
    print("INSTALLER TEST OK")
