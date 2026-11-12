"""Install Music Studio MCP for ACE-Step into the AI agents found on this PC.

Usage (from the app folder):
  uv run mcp/install.py              detect agents and ask which ones to configure
  uv run mcp/install.py --all        configure every detected agent without asking
  uv run mcp/install.py --list       only show what was detected (and where each agent keeps its MCP servers)
  uv run mcp/install.py --uninstall  remove the entry from the detected agents
  uv run mcp/install.py --dry-run    show what would change, change nothing
  uv run mcp/install.py --print      print the configuration to paste into any other agent

Only the Python standard library is used. Every file is backed up (<name>.bak-<time>) before it is changed.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

NAME = "music-studio-mcp-for-ace-step"
TITLE = "Music Studio MCP for ACE-Step"
HERE = Path(__file__).resolve().parent
SERVER = HERE / "music_studio_mcp.py"
HOME = Path.home()
APPDATA = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))
VERIFIED = {"Claude Code", "Codex"}  # tested end to end by the authors; the others use their documented format


def _italian():
    try:
        return (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) == 0x10
    except Exception:
        return os.environ.get("LANG", "").startswith("it")


IT = _italian()


def msg(en, it):
    return it if IT else en


def find_uv():
    uv = shutil.which("uv") or str(HOME / ".local" / "bin" / ("uv.exe" if os.name == "nt" else "uv"))
    return uv if Path(uv).is_file() else None


def server_command(uv):
    return uv, ["run", "--script", str(SERVER)]


# ------------------------------------------------------------------ entry formats


def entry_for(fmt, uv):
    cmd, args = server_command(uv)
    if fmt == "vscode":  # VS Code / Copilot Chat mcp.json
        return {"type": "stdio", "command": cmd, "args": args}
    if fmt == "copilot":  # GitHub Copilot CLI ~/.copilot/mcp-config.json
        return {"type": "local", "command": cmd, "args": args, "tools": ["*"]}
    if fmt == "zed":  # Zed settings.json context_servers
        return {"source": "custom", "command": cmd, "args": args, "env": {}}
    if fmt == "opencode":  # opencode.json "mcp"
        return {"type": "local", "command": [cmd, *args], "enabled": True}
    return {"command": cmd, "args": args}  # the common "mcpServers" format


# ------------------------------------------------------------------ agents
# (name, kind, path, json key, entry format). kind: json | toml | yaml | cli


def _vscode_family():
    """VS Code (stable and Insiders) and the extensions that keep their own MCP file inside it."""
    out = []
    for edition in ("Code", "Code - Insiders"):
        user = APPDATA / edition / "User"
        if not user.is_dir():
            continue
        label = "VS Code" + (" Insiders" if "Insiders" in edition else "")
        out.append((f"{label} (Copilot Chat)", "json", user / "mcp.json", "servers", "vscode"))
        gs = user / "globalStorage"
        exts = [("Cline", "saoudrizwan.claude-dev", ["cline_mcp_settings.json"]),
                ("Roo Code", "rooveterinaryinc.roo-cline", ["mcp_settings.json", "cline_mcp_settings.json"]),
                ("Kilo Code", "kilocode.kilo-code", ["mcp_settings.json"])]
        for ext_name, ext_id, files in exts:
            if (gs / ext_id).is_dir():
                settings = gs / ext_id / "settings"
                path = next((settings / f for f in files if (settings / f).exists()), settings / files[0])
                out.append((f"{ext_name} ({label})", "json", path, "mcpServers", "std"))
    return out


def agents():
    found = []
    # Claude Desktop: classic installer and Microsoft Store package (which keeps its own copy of the config)
    desk = [APPDATA / "Claude"] if (APPDATA / "Claude").is_dir() else []
    desk += [p / "LocalCache" / "Roaming" / "Claude" for p in LOCALAPPDATA.joinpath("Packages").glob("Claude_*")]
    for d in desk:
        found.append(("Claude Desktop", "json", d / "claude_desktop_config.json", "mcpServers", "std"))
    # Claude Code (CLI, VS Code and JetBrains extensions share the user config): prefer its own CLI
    claude = shutil.which("claude") or next((str(p) for p in [HOME / ".local/bin/claude.exe"] if p.is_file()), None)
    if claude:
        found.append(("Claude Code", "cli", Path(claude), "", ""))
    elif (HOME / ".claude.json").is_file():
        found.append(("Claude Code", "json", HOME / ".claude.json", "mcpServers", "std"))
    # Codex (CLI, IDE extension and desktop app share ~/.codex/config.toml)
    if (HOME / ".codex").is_dir() or shutil.which("codex"):
        found.append(("Codex", "toml", HOME / ".codex" / "config.toml", "", ""))
    simple = [  # (name, folder that proves it is installed, config file, json key, format)
        ("Gemini CLI", HOME / ".gemini", HOME / ".gemini" / "settings.json", "mcpServers", "std"),
        ("Antigravity", HOME / ".gemini" / "antigravity", HOME / ".gemini" / "antigravity" / "mcp_config.json", "mcpServers", "std"),
        ("Qwen Code", HOME / ".qwen", HOME / ".qwen" / "settings.json", "mcpServers", "std"),
        ("GitHub Copilot CLI", HOME / ".copilot", HOME / ".copilot" / "mcp-config.json", "mcpServers", "copilot"),
        ("Cursor", HOME / ".cursor", HOME / ".cursor" / "mcp.json", "mcpServers", "std"),
        ("Windsurf", HOME / ".codeium" / "windsurf", HOME / ".codeium" / "windsurf" / "mcp_config.json", "mcpServers", "std"),
        ("Kiro", HOME / ".kiro", HOME / ".kiro" / "settings" / "mcp.json", "mcpServers", "std"),
        ("Amazon Q Developer", HOME / ".aws" / "amazonq", HOME / ".aws" / "amazonq" / "mcp.json", "mcpServers", "std"),
        ("LM Studio", HOME / ".lmstudio", HOME / ".lmstudio" / "mcp.json", "mcpServers", "std"),
        ("opencode", HOME / ".config" / "opencode", HOME / ".config" / "opencode" / "opencode.json", "mcp", "opencode"),
        ("Zed", APPDATA / "Zed", APPDATA / "Zed" / "settings.json", "context_servers", "zed"),
    ]
    for name, marker, path, key, fmt in simple:
        if marker.is_dir():
            found.append((name, "json", path, key, fmt))
    found += _vscode_family()
    if (HOME / ".continue").is_dir():
        found.append(("Continue", "yaml", HOME / ".continue" / "config.yaml", "", ""))
    return found


# ------------------------------------------------------------------ editing


def backup(path: Path):
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}"))


def write(path: Path, text: str, dry: bool):
    if not dry:
        backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def edit_json(path: Path, key: str, entry: dict | None, dry: bool) -> str:
    data = {}
    if path.exists():
        text = path.read_text(encoding="utf-8-sig").strip()
        if text:
            try:
                data = json.loads(text)
            except ValueError:
                raise RuntimeError(msg(
                    f"not changed: {path} is not plain JSON (comments?). Add the entry by hand (--print).",
                    f"non modificato: {path} non è JSON semplice (commenti?). Aggiungi la voce a mano (--print)."))
    servers = data.setdefault(key, {})
    if entry is None:
        if NAME not in servers:
            return msg("nothing to remove", "niente da rimuovere")
        del servers[NAME]
    else:
        servers[NAME] = entry
    write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n", dry)
    return str(path)


TOML_BLOCK = re.compile(r"(?ms)^\[mcp_servers\.%s\]\s*\n.*?(?=^\[|\Z)" % re.escape(NAME))


def toml_str(s):
    return "'" + s + "'" if "'" not in s else json.dumps(s)  # literal string keeps Windows backslashes


def edit_toml(path: Path, uv: str | None, dry: bool) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    new = TOML_BLOCK.sub("", text).rstrip()
    if uv:
        cmd, args = server_command(uv)
        new += ("\n\n" if new else "") + (
            f"[mcp_servers.{NAME}]\ncommand = {toml_str(cmd)}\n"
            f"args = [{', '.join(toml_str(a) for a in args)}]\n"
            "startup_timeout_sec = 120\ntool_timeout_sec = 120\n")
    elif new == text.rstrip():
        return msg("nothing to remove", "niente da rimuovere")
    write(path, new.rstrip() + "\n", dry)
    return str(path)


def yaml_str(s):
    return "'" + s.replace("'", "''") + "'"


def edit_continue_yaml(path: Path, uv: str | None, dry: bool) -> str:
    """Continue's config.yaml: `mcpServers` is a list of items with a `name`. Our item is added/removed as a
    self-contained block of lines, without rewriting the rest of the user's file."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    # remove our previous item (from its "- name:" line to the next item or the next top-level key)
    out, skip = [], False
    for ln in lines:
        if re.match(r"^\s*-\s+name:\s*['\"]?%s['\"]?\s*$" % re.escape(NAME), ln):
            skip = True
            continue
        if skip and (re.match(r"^\s*-\s", ln) or re.match(r"^\S", ln)):
            skip = False
        if not skip:
            out.append(ln)
    if uv:
        cmd, args = server_command(uv)
        item = [f"  - name: {NAME}", "    type: stdio", f"    command: {yaml_str(cmd)}", "    args:"]
        item += [f"      - {yaml_str(a)}" for a in args]
        idx = next((i for i, ln in enumerate(out) if re.match(r"^mcpServers:\s*$", ln)), None)
        if idx is None:
            if any(re.match(r"^mcpServers:", ln) for ln in out):
                raise RuntimeError(msg("not changed: unusual mcpServers syntax in config.yaml, add it by hand",
                                       "non modificato: mcpServers in config.yaml ha una forma insolita, aggiungilo a mano"))
            out += ["", "mcpServers:"] + item
        else:
            end = idx + 1
            while end < len(out) and (out[end].startswith((" ", "\t", "-")) or not out[end].strip()):
                end += 1
            while end > idx + 1 and not out[end - 1].strip():
                end -= 1
            out[end:end] = item
    elif out == lines:
        return msg("nothing to remove", "niente da rimuovere")
    write(path, "\n".join(out).rstrip() + "\n", dry)
    return str(path)


def claude_cli(exe: Path, uv: str | None, dry: bool) -> str:
    if not dry:
        subprocess.run([str(exe), "mcp", "remove", "--scope", "user", NAME], capture_output=True, text=True)
    if uv is None:
        return msg("removed with `claude mcp remove`", "rimosso con `claude mcp remove`")
    cmd, args = server_command(uv)
    full = [str(exe), "mcp", "add", "--scope", "user", NAME, "--", cmd, *args]
    if dry:
        return " ".join(full)
    r = subprocess.run(full, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return f"claude mcp add --scope user {NAME}"


def apply(agent, uv, dry):
    name, kind, path, key, fmt = agent
    try:
        if kind == "cli":
            where = claude_cli(path, uv, dry)
        elif kind == "toml":
            where = edit_toml(path, uv, dry)
        elif kind == "yaml":
            where = edit_continue_yaml(path, uv, dry)
        else:
            where = edit_json(path, key, entry_for(fmt, uv) if uv else None, dry)
        print(f"  [ok] {name}: {where}")
    except Exception as e:
        print(f"  [!!] {name}: {e}")


def print_config(uv):
    cmd, args = server_command(uv or "uv")
    print(msg("Generic configuration (most agents use this JSON format):",
              "Configurazione generica (la maggior parte degli agenti usa questo formato JSON):"))
    print(json.dumps({"mcpServers": {NAME: {"command": cmd, "args": args}}}, indent=2))
    print(msg("\nCommand line form:", "\nForma a riga di comando:"), cmd, " ".join(f'"{a}"' for a in args))


def main():
    ap = argparse.ArgumentParser(description=f"Install {TITLE} into AI agents")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--print", action="store_true")
    a = ap.parse_args()

    uv = find_uv()
    if a.print:
        return print_config(uv)
    if not uv and not a.uninstall:
        sys.exit(msg("uv not found: install it from https://docs.astral.sh/uv/ and run this again.",
                     "uv non trovato: installalo da https://docs.astral.sh/uv/ e riesegui."))
    if not SERVER.is_file():
        sys.exit(f"{SERVER} missing")

    found = agents()
    print(msg(f"{TITLE} — AI agents found on this PC:", f"{TITLE} — agenti AI trovati su questo PC:"))
    if not found:
        print(msg("  none. Use --print and add the configuration to your agent by hand.",
                  "  nessuno. Usa --print e aggiungi la configurazione al tuo agente a mano."))
        return
    for i, (name, kind, path, _, _) in enumerate(found, 1):
        tag = msg("verified", "verificato") if name in VERIFIED else msg("not verified", "non verificato")
        print(f"  {i}. {name} [{tag}]  ->  {path}")
    if a.list:
        return

    chosen = found
    if not a.all:
        ans = input(msg("\nWhich ones? Numbers separated by commas, Enter = all, q = quit: ",
                        "\nQuali? Numeri separati da virgola, Invio = tutti, q = esci: ")).strip().lower()
        if ans == "q":
            return
        if ans:
            idx = {int(x) for x in re.findall(r"\d+", ans)}
            chosen = [ag for i, ag in enumerate(found, 1) if i in idx]

    if not a.uninstall and not a.dry_run:
        print(msg("\nPreparing the MCP server (first time downloads its Python packages)…",
                  "\nPreparazione del server MCP (la prima volta scarica i pacchetti Python)…"))
        subprocess.run([uv, "sync", "--script", str(SERVER)], check=False)

    print(msg("\nRemoving:" if a.uninstall else "\nConfiguring:", "\nRimozione:" if a.uninstall else "\nConfigurazione:")
          + (msg(" (dry run, nothing is changed)", " (prova, nessuna modifica)") if a.dry_run else ""))
    for ag in chosen:
        apply(ag, None if a.uninstall else uv, a.dry_run)
    if not a.dry_run:
        print(msg("\nDone. Restart the agents (close and reopen the app or the terminal session).",
                  "\nFatto. Riavvia gli agenti (chiudi e riapri l'app o la sessione del terminale)."))


if __name__ == "__main__":
    main()
