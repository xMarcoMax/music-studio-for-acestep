# Music Studio MCP for ACE-Step

**English** · [Italiano](README.it.md)

Technical name: `music-studio-mcp-for-ace-step` · Version **1.1.0**

An [MCP](https://modelcontextprotocol.io) server that lets an AI agent create music with ACE-Step 1.5 on your PC.
You describe the song in the chat; the agent asks which mode to use (Simple, Custom, Remix, Repaint…), asks a few
questions (style, vocals, language, approximate length, loop, audio files…), writes the style tags and the lyrics,
shows you a summary, asks the file name and, after your OK, generates the song through the
**Music Studio for ACE-Step** app.

> [!TIP]
> **Exclusive to this MCP: songs that loop seamlessly.** ACE-Step and the app cannot make them (ACE-Step fades out at
> the end even when asked for a loop); with the MCP you ask for a song "that loops forever" and get one `.wav` whose
> end flows into its beginning — see [Seamless loops](#seamless-loops).

## Supported agents

| Agent | Status |
|---|---|
| Claude Code | **verified** |
| Codex (CLI, IDE extension, desktop app) | **verified** |
| Claude Desktop, Gemini CLI, Qwen Code, GitHub Copilot CLI, VS Code (Copilot Chat), Cline, Roo Code, Kilo Code, Cursor, Windsurf, Kiro, Amazon Q Developer, LM Studio, opencode, Continue, Antigravity, Zed | not verified — configured with each agent's documented format, they should work |

Any other agent that supports stdio MCP servers works with the generic configuration (see *Manual install*).

## Requirements

- **Music Studio for ACE-Step open** while you use the agent, with `"enable_api": true` in its `config.json`
  (the default). Wait until the ACE-Step page is visible.
- [uv](https://docs.astral.sh/uv/) (already needed by ACE-Step). The server is the single file
  `mcp/music_studio_mcp.py`; uv downloads its only dependency (`mcp`) the first time.
- ffmpeg for seamless loops (`winget install Gyan.FFmpeg`; ACE-Step needs it anyway).

## Install (automatic)

Open a terminal in the app folder (the one with `Music Studio.exe`, or the repository root) and run:

```powershell
uv run mcp\install.py
```

The installer finds the AI agents installed on the PC — desktop apps, command-line tools and VS Code extensions —
shows where each one keeps its MCP servers, and asks which ones to configure (Enter = all). Every file is backed up
(`<file>.bak-<date>`) before it is changed. Then **restart the agents**.

| Option | Effect |
|---|---|
| `--list` | only show the detected agents and their config files |
| `--all` | configure all detected agents without asking |
| `--dry-run` | show what would change, change nothing |
| `--uninstall` | remove the server from the agents |
| `--print` | print the configuration for any other agent |

Where it writes:

| Agent | File |
|---|---|
| Claude Code | `claude mcp add --scope user` (or `~/.claude.json`) |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` (+ the Microsoft Store copy in `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\`) |
| Codex | `~/.codex/config.toml` |
| Gemini CLI / Qwen Code | `~/.gemini/settings.json` / `~/.qwen/settings.json` |
| Antigravity | `~/.gemini/antigravity/mcp_config.json` |
| GitHub Copilot CLI | `~/.copilot/mcp-config.json` |
| VS Code (Copilot Chat) | `%APPDATA%\Code\User\mcp.json` (also *Code - Insiders*) |
| Cline / Roo Code / Kilo Code | their `settings` file inside VS Code's `globalStorage` |
| Cursor / Windsurf | `~/.cursor/mcp.json` / `~/.codeium/windsurf/mcp_config.json` |
| Kiro / Amazon Q Developer | `~/.kiro/settings/mcp.json` / `~/.aws/amazonq/mcp.json` |
| LM Studio | `~/.lmstudio/mcp.json` |
| opencode | `~/.config/opencode/opencode.json` |
| Continue | `~/.continue/config.yaml` |
| Zed | `%APPDATA%\Zed\settings.json` (usually has comments: the installer leaves it alone, add it by hand) |

## Install (manual)

Replace `C:\path\to\Music Studio` with your folder. If the agent cannot find `uv`, use its full path
(`where uv` prints it, usually `C:\Users\<you>\.local\bin\uv.exe`).

**Claude Code**

```powershell
claude mcp add --scope user music-studio-mcp-for-ace-step -- uv run --script "C:\path\to\Music Studio\mcp\music_studio_mcp.py"
```

**Codex** — `~/.codex/config.toml`:

```toml
[mcp_servers.music-studio-mcp-for-ace-step]
command = 'uv'
args = ['run', '--script', 'C:\path\to\Music Studio\mcp\music_studio_mcp.py']
startup_timeout_sec = 120
tool_timeout_sec = 120
```

**Most other agents** (Claude Desktop, Gemini CLI, Cursor, Windsurf, Cline, Kiro, LM Studio, …) — in their
`mcpServers` file:

```json
{
  "mcpServers": {
    "music-studio-mcp-for-ace-step": {
      "command": "uv",
      "args": ["run", "--script", "C:\\path\\to\\Music Studio\\mcp\\music_studio_mcp.py"]
    }
  }
}
```

VS Code uses `"servers"` with `"type": "stdio"`; GitHub Copilot CLI uses `"type": "local"` and `"tools": ["*"]`;
Zed uses `"context_servers"` with `"source": "custom"`. `uv run mcp\install.py --print` prints the exact command.

## How to use it

1. Open Music Studio for ACE-Step and wait for the ACE-Step page.
2. Ask the agent in your own words — no special command is needed, for example:
   - *"Use Music Studio to make me a 1-minute relaxing lo-fi track to study with"*
   - *"Write and generate an Italian pop song about summer, female voice, about 2 minutes"*
   - *"Remix C:\Music\my-song.mp3 as an acoustic folk version"*
3. The agent checks ACE-Step and asks which **mode** to use (it skips the question when your request already says it).
4. It asks only the questions of that mode — style, vocals and language, **approximate length with the maximum in
   brackets** (e.g. *"Length? (max 8 min)"*, or let ACE-Step choose), optional **seamless loop**, tempo/key,
   number of versions, and the audio files the mode needs.
5. It shows a summary table and waits for your OK; then, as the **last question**, it asks the **file name**.
6. It generates (a 30–60 s song takes about a minute; the app shows a progress window) and tells you where the
   files are.

### Modes

| Mode | What it does | Needs |
|---|---|---|
| **Simple** | Describe the song in your own words; ACE-Step writes style, lyrics, length, tempo and key | — |
| **Custom** | Full control: style, lyrics, length, tempo, key | optional **reference audio** to imitate its sound |
| **Remix** | Turns an existing song into another style, keeping its structure/melody (faithfulness 0.2 loose – 0.8 faithful) | a **source song** |
| **Repaint** | Regenerates only a time range (from second X to second Y) and keeps the rest | a **source song** |
| **Extract** | Isolates one instrument or the vocals | a source song, **base model** only |
| **Lego** | Adds or replaces one track (e.g. drums) | a source song, **base model** only |
| **Complete** | Adds the missing instruments to a partial song | a source song, **base model** only |

Extract, Lego and Complete appear only when ACE-Step runs a *base* model (the turbo model offers the first four).

### Audio files (source song, reference audio)

The agent cannot read files attached to the chat: **paste the full path** of the file when it asks, e.g.
`C:\Users\Name\Music\song.mp3` (in a terminal-based agent you can drag the file into the window and the path is
typed for you). You can also ask the agent to **list your recent songs** and pick one of them as the source.

### File names and where the songs are saved

ACE-Step names files with random codes; the server renames the song with the name you choose. One song = **one
file**, `<name>.mp3` (`<name>.wav` for a loop). Only if you ask for more versions of the same song are the others
called `<name>_2.mp3`, `<name>_3.mp3`, … They are saved in ACE-Step's output folder,
in `gradio_outputs\mcp_<date>_<time>_<name>\` (with ACE-Step's side files); the agent tells you the full path, and
*Open generated songs folder* in the app menu opens `gradio_outputs`.

Some clients also offer the ready-made prompt **compose_song** (in Claude Code: `/mcp__music-studio-mcp-for-ace-step__compose_song`).

### Lyrics and languages

You can talk to the agent in any language. ACE-Step understands the musical style best as English tags, so the
agent translates your description into English tags; the **lyrics** stay in the language you choose for the vocals
(Italian, Spanish, Japanese, …). For the lyrics you can choose:

- **the agent writes them** from your topic;
- **you provide them**: paste your text — the agent uses your words exactly and only adds section tags if missing;
- **ACE-Step improvises them** (its own language model writes tags, lyrics and length).

ACE-Step lyrics are split into sections with tags on their own line, e.g. `[Intro]`, `[Verse 1]`, `[Chorus]`,
`[Bridge]`, `[Outro]`; descriptors such as `[Chorus - anthemic]` are allowed. Instrumental songs have no lyrics.

### Seamless loops

ACE-Step cannot make a song whose end joins its beginning on its own: even with "seamless loop" in the prompt it
tends to fade out at the end. When you ask for a loop, the agent adds loop-friendly tags (no intro, no outro, steady
energy) and you still get **one file**, `<name>.wav`, ready to loop: the song is cut to whole bars and its last
bar is blended into the first one, so the end flows into the beginning and it can repeat forever (like video game
music). WAV is used because MP3 adds tiny silences at the edges that break gapless playback.

### Tools

| Tool | What it does |
|---|---|
| `acestep_status` | Is ACE-Step reachable? Loaded models, max length (e.g. "8 min"), max versions, available modes |
| `acestep_ask_song_details` | The questions for the chosen mode (a form for Custom in clients that support it) |
| `acestep_generate` | Generates in the chosen mode with the chosen file name, optional seamless loop; returns paths and folder, or a job id |
| `acestep_get_result` | Waits for a running generation |
| `acestep_list_songs` | Latest generated songs (to pick a source song for Remix/Repaint) |

Simple mode and Custom without reference audio use ACE-Step's REST API; the modes with audio files use the
generation function of ACE-Step's own page, whose parameters the server reads from the page every time.

## Notes

- One generation at a time; while the agent generates, the ACE-Step page in the app is busy until it finishes.
- The maximum length depends on your GPU and loaded models (the app shows it in the menu bar).
- Nothing leaves your PC: the server only talks to ACE-Step on `127.0.0.1`. It reads URL, models and limits from
  `server_info.json`, written by the app next to `config.json`. `ACESTEP_URL` overrides the address.

## Troubleshooting

- *"ACE-Step is not reachable"*: open the app and wait for the page. If you start ACE-Step by hand, add `--enable-api`.
- The agent does not show the tools: restart it; check that `uv` is on the PATH or use its full path.
- First start is slow: uv is downloading the `mcp` package (the installer does it in advance).
- Codex says the server did not start in time: keep `startup_timeout_sec = 120`.

Uninstall: `uv run mcp\install.py --uninstall`.
