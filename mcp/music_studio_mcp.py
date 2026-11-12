# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.3,<3"]
# ///
"""Music Studio MCP for ACE-Step (technical name: music-studio-mcp-for-ace-step).

Lets AI agents (Claude, Codex, Gemini CLI, Cursor, ...) generate music with the ACE-Step 1.5 server started by
the Music Studio for ACE-Step app (or by `uv run acestep --enable-api`).

Run:  uv run --script mcp/music_studio_mcp.py     (stdio transport)
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, create_model

from mcp.server.mcpserver import AcceptedElicitation, Context, MCPServer

VERSION = "1.0.0"  # same as version.py of the app
HERE = Path(__file__).resolve().parent
DEFAULT_URL = "http://127.0.0.1:7860"
WAIT_SECONDS = 45  # return a job id instead of blocking longer: some clients time out tool calls around 60 s
HTTP_TIMEOUT = 3600
AUDIO_EXT = {".mp3", ".flac", ".wav", ".opus", ".aac", ".ogg", ".m4a"}
LANGUAGES = ["en", "it", "es", "fr", "de", "pt", "ja", "ko", "zh", "ru", "unknown"]

INSTRUCTIONS = """\
ACE-Step generates songs (music, optionally with sung lyrics) on the user's own PC.
The Music Studio for ACE-Step app must be open. Always talk to the user in their language.

Recommended flow:
1. Call acestep_status to learn the loaded model and the maximum song length.
2. Collect the song details. Call acestep_ask_song_details: in clients that support forms it shows one;
   otherwise it returns the questions to ask. Ask them in a short, friendly way (a numbered list or a
   small table with options), skip what the user already said, and suggest sensible defaults.
   Ask for an approximate length and show the maximum in brackets, e.g. "Length? (max 8 min)"; the user may
   also let ACE-Step choose it (then omit duration_seconds).
3. Write the inputs yourself: `caption` = comma-separated English style tags (genre, mood, instruments,
   vocal type, tempo feel, production), translated to English whatever language the user speaks;
   `lyrics` = lyrics in the chosen vocal language, split into sections with tags on their own line:
   [Intro], [Verse 1], [Pre-Chorus], [Chorus], [Verse 2], [Bridge], [Outro] (descriptors are allowed, e.g.
   [Chorus - anthemic], [Verse - whispered]); for instrumental songs leave lyrics empty and set instrumental=true.
   If the user gives their own lyrics, use their words exactly (do not translate or rewrite them); only add the
   section tags if they are missing, and say so in the summary.
4. Show the user a compact summary table (style, vocals/language, length, BPM, key, variants, loop) and the
   lyrics, and ask for confirmation before generating.
5. Call acestep_generate. If it returns a job id, call acestep_get_result until it is done (a 30-60 s song
   usually takes about 1 minute). Then give the user the file path(s).

Seamless loops (video game levels, menus, background music that must never end): set make_loop=true, keep it
instrumental, and add caption tags such as "seamless loop, loopable, steady energy, no intro, no outro,
no fade in, no fade out". The server then also writes a <name>_loop.wav whose end flows into its start.
"""

mcp = MCPServer(name="music-studio-mcp-for-ace-step", title="Music Studio MCP for ACE-Step", version=VERSION,
                instructions=INSTRUCTIONS)


# ---------------------------------------------------------------- server discovery


def _info_candidates() -> list[Path]:
    dirs = []
    if os.environ.get("ACESTEP_APP_DIR"):
        dirs.append(Path(os.environ["ACESTEP_APP_DIR"]))
    dirs += [HERE.parent, HERE.parent / "dist" / "Music Studio"]
    return [d / "server_info.json" for d in dirs if (d / "server_info.json").is_file()]


def server_info() -> dict:
    """Newest server_info.json written by the desktop app (model, limits, URL, output folder)."""
    files = sorted(_info_candidates(), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def base_url(info: dict) -> str:
    return (os.environ.get("ACESTEP_URL") or info.get("url") or DEFAULT_URL).rstrip("/")


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # local server: never use a proxy


def http_json(url: str, payload: dict | None = None, timeout: float = 10) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with _opener.open(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        raise RuntimeError(f"ACE-Step error {e.code}: {detail}") from None


def max_duration(info: dict) -> int:
    if info.get("lm_model") and info.get("max_duration_with_lm"):
        return int(info["max_duration_with_lm"])
    return int(info.get("max_duration_without_lm") or 600)


def fmt_length(seconds: int) -> str:
    return f"{seconds // 60} min" if seconds % 60 == 0 else f"{seconds // 60}:{seconds % 60:02d} min"


def max_variants(info: dict) -> int:
    key = "max_batch_with_lm" if info.get("lm_model") else "max_batch_without_lm"
    return int(info.get(key) or 2)


def check_server() -> tuple[dict, str]:
    """Return (info, url) or raise a clear error if ACE-Step is not reachable with the API enabled."""
    info = server_info()
    url = base_url(info)
    try:
        http_json(url + "/health", timeout=3)
    except Exception:
        if info and info.get("app_running") is False:
            raise RuntimeError("The Music Studio for ACE-Step app is closed. Ask the user to open it, wait until the ACE-Step page "
                               "is visible, then try again.") from None
        raise RuntimeError(f"ACE-Step is not reachable at {url}. Ask the user to open the Music Studio for ACE-Step app and wait "
                           "until the page is visible. If ACE-Step was started by hand, it needs the "
                           "--enable-api option.") from None
    return info, url


# ---------------------------------------------------------------- generation jobs

_jobs: dict[str, dict] = {}
_gen_lock = threading.Lock()


def _move_outputs(files: list[dict], info: dict) -> list[dict]:
    """ACE-Step's API saves under acestep/ui/gradio_outputs (path bug): move the songs next to the ones
    generated from the page, in <ACE-Step>/gradio_outputs/mcp_<time>/."""
    root = info.get("acestep_outputs")
    if not root:
        return files
    root = Path(root)
    dest = root / f"mcp_{datetime.now():%Y%m%d_%H%M%S}"
    for item in files:
        src = Path(item["file"])
        try:
            if root in src.parents or not src.is_file():
                continue
            dest.mkdir(parents=True, exist_ok=True)
            for sib in src.parent.glob(src.stem + "*"):  # audio + its sidecar files
                shutil.move(str(sib), str(dest / sib.name))
            item["file"] = str(dest / src.name)
            if src.parent.exists() and not any(src.parent.iterdir()):
                src.parent.rmdir()
        except OSError:
            pass  # keep the original path if the move fails
    return files


def find_ffmpeg() -> str | None:
    """ffmpeg from PATH, or from the PATH stored in the Windows registry (agents may start with an old PATH)."""
    found = shutil.which("ffmpeg")
    if found or os.name != "nt":
        return found
    import winreg

    dirs = []
    for root, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(root, key) as k:
                dirs += winreg.ExpandEnvironmentStrings(winreg.QueryValueEx(k, "Path")[0]).split(";")
        except OSError:
            pass
    return shutil.which("ffmpeg", path=";".join(d for d in dirs if d))


def create_loop(src: str, duration: float, bpm: float | None, time_signature: str | None, crossfade: float) -> str:
    """Write <name>_loop.wav: the end is blended (equal power) into the start and the head is cut, so the file's
    end flows into its own start and it can repeat forever without a seam. With a known BPM the song is first
    cut to whole bars and the overlap is one bar, so beats stay aligned across the seam.
    WAV, because MP3 adds silence at the edges that breaks gapless looping."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found: install it (winget install Gyan.FFmpeg) to create loops")
    out = str(Path(src).with_name(Path(src).stem + "_loop.wav"))
    length = duration
    if bpm and bpm > 0:
        bar = (int(time_signature) if str(time_signature or "").isdigit() else 4) * 60.0 / bpm
        bars = int(duration // bar)
        if bars >= 4:
            length, crossfade = bars * bar, bar
    crossfade = min(crossfade, length / 4)
    x, end = f"{crossfade:.4f}", f"{length:.4f}"
    graph = (f"[0:a]atrim=end={end},asetpts=PTS-STARTPTS,asplit=2[a][b];[a]atrim=start={x},asetpts=PTS-STARTPTS[body];"
             f"[b]atrim=end={x},asetpts=PTS-STARTPTS[head];[body][head]acrossfade=d={x}:c1=qsin:c2=qsin")
    r = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", src, "-filter_complex", graph, "-c:a", "pcm_s16le", out],
                       capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError("ffmpeg loop failed: " + r.stderr.strip()[-300:])
    return out


def _run_job(job_id: str, url: str, payload: dict, info: dict, loop_crossfade: float | None):
    job = _jobs[job_id]
    try:
        with _gen_lock:
            res = http_json(url + "/release_task", payload, timeout=HTTP_TIMEOUT)
            task_id = (res.get("data") or {}).get("task_id")
            q = http_json(url + "/query_result", {"task_id_list": [task_id]}, timeout=30)
        items = json.loads((q.get("data") or [{}])[0].get("result") or "[]")
        if not items:
            raise RuntimeError("ACE-Step returned no audio")
        songs = _move_outputs(items, info)
        if loop_crossfade:
            for s in songs:
                try:
                    s["loop_file"] = create_loop(s["file"], float(s.get("duration") or 30), s.get("bpm"),
                                                 s.get("timesignature"), loop_crossfade)
                except Exception as e:
                    s["loop_error"] = str(e)
        job.update(status="done", songs=songs)
    except Exception as e:
        job.update(status="error", error=str(e))
    job["seconds"] = round(time.monotonic() - job["started"])


def _job_report(job_id: str) -> dict:
    job = _jobs[job_id]
    out = {"job_id": job_id, "status": job["status"]}
    if job["status"] == "running":
        out["elapsed_seconds"] = round(time.monotonic() - job["started"])
        out["next_step"] = "Call acestep_get_result with this job_id to wait for the song."
    elif job["status"] == "done":
        out["generation_seconds"] = job["seconds"]
        out["songs"] = [{
            "file": s["file"], "duration_seconds": s.get("duration"), "bpm": s.get("bpm"),
            "key": s.get("keyscale"), "time_signature": s.get("timesignature"),
            "vocal_language": s.get("vocal_language"), "seed": s.get("seed"),
            "caption_used": s.get("caption"), "lyrics_used": s.get("lyrics"),
            **({"loop_file": s["loop_file"]} if s.get("loop_file") else {}),
            **({"loop_error": s["loop_error"]} if s.get("loop_error") else {}),
        } for s in job["songs"]]
        out["next_step"] = ("Tell the user where the file is. They can also open it from the Music Studio app menu "
                            "'Open generated songs folder'.")
    else:
        out["error"] = job["error"]
    return out


async def _wait(job_id: str, seconds: float, ctx: Context | None) -> dict:
    end = time.monotonic() + seconds
    while _jobs[job_id]["status"] == "running" and time.monotonic() < end:
        await asyncio.sleep(1)
        if ctx is not None:
            try:  # keeps clients that support progress notifications informed (and their timeouts alive)
                await ctx.report_progress(time.monotonic() - _jobs[job_id]["started"], None, "Generating…")
            except Exception:
                pass
    return _job_report(job_id)


# ---------------------------------------------------------------- tools


@mcp.tool()
def acestep_status() -> dict:
    """Check that ACE-Step is running and return the loaded models and limits (max song length,
    max variants per request). Call this first."""
    info = server_info()
    url = base_url(info)
    try:
        http_json(url + "/health", timeout=3)
        reachable = True
    except Exception:
        reachable = False
    return {
        "reachable": reachable,
        "mcp_version": VERSION,
        "app_version": info.get("app_version"),
        "url": url,
        "app_running": info.get("app_running"),
        "dit_model": info.get("dit_model"),
        "language_model": info.get("lm_model"),
        "max_song_seconds": max_duration(info),
        "max_song_length": fmt_length(max_duration(info)),
        "max_variants": max_variants(info),
        "ffmpeg_for_loops": bool(find_ffmpeg()),
        "gpu_memory_gb": info.get("gpu_memory_gb"),
        "songs_folder": info.get("acestep_outputs"),
        "generation_running": _gen_lock.locked(),
        "hint": None if reachable else "Ask the user to open the Music Studio for ACE-Step app and wait until the page is visible.",
    }


def _details_model(info: dict):
    limit = max_duration(info)
    return create_model(
        "SongDetails",
        style=(str, Field(description="Genre / style, e.g. lo-fi hip hop, epic orchestral, Italian pop")),
        mood=(str, Field(default="", description="Mood / atmosphere (optional)")),
        instruments=(str, Field(default="", description="Main instruments (optional)")),
        vocals=(Literal["instrumental", "vocals: the AI agent writes the lyrics", "vocals: I provide the lyrics",
                        "vocals: ACE-Step improvises everything"],
                Field(default="instrumental", description="Instrumental or sung")),
        vocal_language=(str, Field(default="en", description="Language of the lyrics: " + ", ".join(LANGUAGES))),
        lyrics_topic=(str, Field(default="", description="What the lyrics are about, or the lyrics themselves")),
        duration_seconds=(int, Field(default=0, ge=0, le=limit,
                                     description=f"Approximate length in seconds (max {fmt_length(limit)}); "
                                                 "0 = let ACE-Step choose")),
        loop=(bool, Field(default=False, description="Seamless loop that can repeat forever (games, background)")),
        bpm=(int, Field(default=0, ge=0, le=300, description="Tempo in BPM, 0 = automatic")),
        key=(str, Field(default="", description="Key, e.g. A minor (empty = automatic)")),
        variants=(int, Field(default=1, ge=1, le=max_variants(info), description="How many versions to generate")),
    )


@mcp.tool()
async def acestep_ask_song_details(ctx: Context, idea: str = "") -> dict:
    """Collect the song details from the user. Shows a form in clients that support MCP elicitation;
    otherwise returns the questions the agent should ask in the chat. `idea` = what the user already said."""
    info = server_info()
    caps = ctx.client_capabilities
    if caps is not None and getattr(caps, "elicitation", None) is not None:
        try:
            res = await ctx.elicit(
                message=("Describe the song to generate" + (f" (idea: {idea})" if idea else "")
                         + ". Leave optional fields empty to let ACE-Step decide."),
                schema=_details_model(info))
            if isinstance(res, AcceptedElicitation):
                return {"answers": res.data.model_dump(),
                        "next_step": "Write caption and lyrics from these answers, show the summary table to the "
                                     "user, ask for confirmation, then call acestep_generate."}
            return {"answers": None, "user_action": res.action,
                    "next_step": "The user closed the form: ask in the chat what they want instead."}
        except Exception:
            pass  # fall back to questions in the chat
    limit = max_duration(info)
    return {
        "form_supported": False,
        "ask_the_user": [
            "Genre / style (e.g. lo-fi, rock, epic orchestral, Italian pop)?",
            "Mood or atmosphere?",
            "Main instruments (optional)?",
            "Instrumental or with vocals? If vocals: shall I write the lyrics, will you provide them, "
            "or should ACE-Step improvise them?",
            "Language of the lyrics (" + ", ".join(LANGUAGES[:-1]) + ")?",
            "What should the lyrics be about?",
            f"Approximate length? (max {fmt_length(limit)}) — or should ACE-Step choose it?",
            "Should it loop seamlessly, like video game or background music that never ends?",
            "Tempo (BPM) and key, or automatic?",
            f"How many versions (1-{max_variants(info)})?",
        ],
        "how_to_ask": "Ask only what is still unknown, in the user's language, as a short numbered list or a "
                      "small table with suggested defaults. Then show a summary and ask for confirmation.",
        "idea_so_far": idea,
    }


@mcp.tool()
async def acestep_generate(
    ctx: Context,
    caption: str,
    lyrics: str = "",
    instrumental: bool = False,
    duration_seconds: Optional[float] = None,
    bpm: Optional[int] = None,
    key: Optional[str] = None,
    time_signature: Optional[Literal["2", "3", "4", "6"]] = None,
    vocal_language: str = "en",
    variants: int = 1,
    audio_format: Literal["mp3", "flac", "wav"] = "mp3",
    seed: Optional[int] = None,
    let_acestep_write: bool = False,
    make_loop: bool = False,
    loop_crossfade_seconds: float = 2.0,
) -> dict:
    """Generate a song with ACE-Step. Confirm the details with the user first.

    caption: English style tags/description of the sound (genre, mood, instruments, vocals, production).
    lyrics: lyrics with [verse]/[chorus]/[bridge] tags in `vocal_language`; leave empty if instrumental.
    duration_seconds: song length (see acestep_status for the maximum); omit to let ACE-Step decide.
    let_acestep_write: true = treat `caption` as a free description and let ACE-Step's language model write
      the tags, lyrics and length itself (duration_seconds is then ignored by ACE-Step).
    make_loop: also write <name>_loop.wav that repeats seamlessly (needs ffmpeg). Add loop-friendly tags to
      the caption (seamless loop, steady energy, no intro, no outro, no fade).
    loop_crossfade_seconds: overlap used to join the end to the start when the BPM is unknown (0.5-8 s);
      with a BPM the loop is cut to whole bars and the overlap is one bar.
    Returns the song file path(s), or a job_id to pass to acestep_get_result if it takes longer.
    """
    info, url = check_server()
    if _gen_lock.locked():
        running = [j for j, v in _jobs.items() if v["status"] == "running"]
        return {"error": "Another song is being generated.", "running_job_id": running[0] if running else None}
    limit = max_duration(info)
    if duration_seconds is not None and not 10 <= duration_seconds <= limit:
        return {"error": f"duration_seconds must be between 10 and {limit} with the loaded models."}
    if not 1 <= variants <= max_variants(info):
        return {"error": f"variants must be between 1 and {max_variants(info)}."}
    if bpm is not None and not 30 <= bpm <= 300:
        return {"error": "bpm must be between 30 and 300."}
    if vocal_language not in LANGUAGES:
        return {"error": "vocal_language must be one of: " + ", ".join(LANGUAGES)}
    if not caption.strip():
        return {"error": "caption is required."}
    if make_loop and not 0.5 <= loop_crossfade_seconds <= 8:
        return {"error": "loop_crossfade_seconds must be between 0.5 and 8."}
    if make_loop and not find_ffmpeg():
        return {"error": "make_loop needs ffmpeg: ask the user to install it (winget install Gyan.FFmpeg)."}

    payload = {"batch_size": variants, "audio_format": audio_format, "vocal_language": vocal_language,
               "thinking": bool(info.get("lm_model", True)), "use_random_seed": seed is None}
    if seed is not None:
        payload["seed"] = seed
    if let_acestep_write:
        payload["sample_query"] = caption + (" (instrumental)" if instrumental else "")
    else:
        payload.update(prompt=caption, lyrics="[Instrumental]" if instrumental or not lyrics.strip() else lyrics)
        if duration_seconds is not None:
            payload["audio_duration"] = duration_seconds
        if bpm:
            payload["bpm"] = bpm
        if key:
            payload["key_scale"] = key
        if time_signature:
            payload["time_signature"] = time_signature

    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {"status": "running", "started": time.monotonic()}
    threading.Thread(target=_run_job, args=(job_id, url, payload, info,
                                            loop_crossfade_seconds if make_loop else None), daemon=True).start()
    return await _wait(job_id, WAIT_SECONDS, ctx)


@mcp.tool()
async def acestep_get_result(ctx: Context, job_id: str, wait_seconds: int = WAIT_SECONDS) -> dict:
    """Wait for a generation started by acestep_generate and return the song file path(s)."""
    if job_id not in _jobs:
        return {"error": f"Unknown job_id {job_id} (jobs are lost if the MCP server restarts)."}
    return await _wait(job_id, max(0, min(wait_seconds, WAIT_SECONDS)), ctx)


@mcp.tool()
def acestep_list_songs(limit: int = 10) -> dict:
    """List the most recent songs in ACE-Step's output folder (newest first)."""
    folder = server_info().get("acestep_outputs")
    if not folder or not os.path.isdir(folder):
        return {"error": "Songs folder unknown: open the Music Studio for ACE-Step app once."}
    files = [p for p in Path(folder).rglob("*") if p.suffix.lower() in AUDIO_EXT]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return {"folder": folder, "songs": [
        {"file": str(p), "created": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")}
        for p in files[:max(1, min(limit, 100))]]}


@mcp.prompt(title="Compose a song with Music Studio for ACE-Step")
def compose_song(idea: str = "") -> str:
    """Guided interview to create a song with ACE-Step."""
    return ("Help me create a song with ACE-Step. " + (f"My idea: {idea}. " if idea else "")
            + "Follow the Music Studio flow: check acestep_status, collect the missing details with "
              "acestep_ask_song_details (ask me in my language; show the maximum length in brackets), write caption "
              "and lyrics, show me a summary table and wait for my confirmation, then generate with acestep_generate "
              "(make_loop=true if I want music that loops forever).")


if __name__ == "__main__":
    mcp.run("stdio")
