# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2.3,<3"]
# ///
"""Music Studio MCP for ACE-Step (technical name: music-studio-mcp-for-ace-step).

Lets AI agents (Claude, Codex, Gemini CLI, Cursor, ...) generate music with the ACE-Step 1.5 server started by
the Music Studio for ACE-Step app (or by `uv run acestep --enable-api`).

Two ACE-Step interfaces are used:
- its REST API (/release_task) for Simple mode and Custom mode without reference audio;
- the generation function of its own web page (Gradio "generation_wrapper") for every mode that needs audio
  files (Custom with reference audio, Remix, Repaint, Extract, Lego, Complete). Its parameters are read from the
  page every time and matched by label, so they follow ACE-Step updates.

Run:  uv run --script mcp/music_studio_mcp.py     (stdio transport)
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
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

from pydantic import Field, create_model

from mcp.server.mcpserver import AcceptedElicitation, Context, MCPServer

VERSION = "1.1.0"  # same as version.py of the app
HERE = Path(__file__).resolve().parent
DEFAULT_URL = "http://127.0.0.1:7860"
WAIT_SECONDS = 45  # return a job id instead of blocking longer: some clients time out tool calls around 60 s
HTTP_TIMEOUT = 3600
AUDIO_EXT = {".mp3", ".flac", ".wav", ".opus", ".aac", ".ogg", ".m4a"}
LANGUAGES = ["en", "it", "es", "fr", "de", "pt", "ja", "ko", "zh", "ru", "unknown"]
TRACKS = ["vocals", "backing_vocals", "drums", "bass", "guitar", "keyboard", "percussion", "strings", "synth",
          "fx", "brass", "woodwinds"]

# mode -> (ACE-Step page mode name, task type, needs a source audio, base models only, one-line description)
MODES = {
    "simple": ("Simple", "text2music", False, False,
               "Describe the song in your own words; ACE-Step writes style, lyrics, length, tempo and key by itself."),
    "custom": ("Custom", "text2music", False, False,
               "Full control: style, lyrics, length, tempo, key; optional reference audio to imitate its sound."),
    "remix": ("Remix", "cover", True, False,
              "Start from an existing song and turn it into another style while keeping its structure/melody."),
    "repaint": ("Repaint", "repaint", True, False,
                "Regenerate only a time range (from second X to second Y) of an existing song, keeping the rest."),
    "extract": ("Extract", "extract", True, True,
                "Isolate one instrument or the vocals from an existing song (base models only)."),
    "lego": ("Lego", "lego", True, True,
             "Add or replace one track (e.g. drums) in an existing song (base models only)."),
    "complete": ("Complete", "complete", True, True,
                 "Complete a partial song with the missing instruments (base models only)."),
}
INSTRUCTION = {  # same texts ACE-Step uses for each task
    "text2music": "Fill the audio semantic mask based on the given conditions:",
    "repaint": "Repaint the mask area based on the given conditions:",
    "cover": "Generate audio semantic tokens based on the given conditions:",
}

INSTRUCTIONS = """\
ACE-Step generates songs (music, optionally with sung lyrics) on the user's own PC.
The Music Studio for ACE-Step app must be open. Always talk to the user in their language.

Recommended flow:
1. Call acestep_status: it returns the loaded model, the maximum song length and the available MODES.
2. Your FIRST question is only the mode: list EVERY available mode from acestep_status (Simple, Custom, Remix,
   Repaint, + Extract, Lego, Complete with base models), each with its one-line description translated to the
   user's language, and ask which one they want (suggest Simple/Custom for a new song, Remix/Repaint to work on an
   existing one). Do not ask anything else in that message. Skip it only if the request already names the mode or
   clearly implies it (e.g. "remix this file").
3. Call acestep_ask_song_details(mode=...): it returns the questions for that mode (or shows a form in clients that
   support it). Ask them in a short, friendly way (a numbered list or a small table), skip what the user already
   said, suggest sensible defaults. Show the maximum length in brackets, e.g. "Length? (max 8 min)".
   Audio files (source song, reference audio): the agent cannot read chat attachments; ask the user to PASTE THE
   FULL PATH of the file, e.g. C:\\Users\\Name\\Music\\song.mp3 (in a terminal they can drag the file into the
   window). They can also pick one of their earlier songs: offer acestep_list_songs.
4. Write the inputs yourself: `caption` = comma-separated English style tags (genre, mood, instruments, vocal type,
   tempo feel, production), translated to English whatever language the user speaks; `lyrics` = lyrics in the
   chosen vocal language, split into sections with tags on their own line: [Intro], [Verse 1], [Pre-Chorus],
   [Chorus], [Verse 2], [Bridge], [Outro] (descriptors allowed, e.g. [Chorus - anthemic]); instrumental songs have
   no lyrics (instrumental=true). If the user gives their own lyrics, use their words exactly; only add missing
   section tags and say so.
5. Show a compact summary table of the choices (mode, files, style, vocals/language, length, BPM, key, variants,
   loop) and ask for confirmation.
6. Only AFTER the user confirmed the summary, ask the file name as a separate last question (without extension),
   suggesting one from the description, e.g. "menu-theme". Never ask it together with the other questions.
7. Call acestep_generate with mode and file_name. If it returns a job id, call acestep_get_result until done (a
   30-60 s song usually takes about 1 minute; the app shows a progress window). Finally tell the user the full
   path of each file, the folder, and that they can also open it from the app menu "Open generated songs folder".

Seamless loops (video game levels, menus, background music that must never end): set make_loop=true, keep it
instrumental, and add caption tags such as "seamless loop, loopable, steady energy, no intro, no outro,
no fade in, no fade out". The result is ONE file, <name>.wav, whose end flows into its start (WAV keeps the loop
gapless; MP3 would add silence at the edges).
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


def is_base_model(info: dict) -> bool:
    return "base" in str(info.get("dit_model") or "").lower()


def available_modes(info: dict) -> list[dict]:
    base = is_base_model(info)
    return [{"mode": k, "name": v[0], "description": v[4], "needs_source_audio": v[2],
             "available": base or not v[3]} for k, v in MODES.items()]


def check_server() -> tuple[dict, str]:
    """Return (info, url) or raise a clear error if ACE-Step is not reachable with the API enabled."""
    info = server_info()
    url = base_url(info)
    try:
        http_json(url + "/health", timeout=3)
    except Exception:
        if info and info.get("app_running") is False:
            raise RuntimeError("The Music Studio for ACE-Step app is closed. Ask the user to open it, wait until "
                               "the ACE-Step page is visible, then try again.") from None
        raise RuntimeError(f"ACE-Step is not reachable at {url}. Ask the user to open the Music Studio for ACE-Step "
                           "app and wait until the page is visible. If ACE-Step was started by hand, it needs the "
                           "--enable-api option.") from None
    return info, url


def audio_path(value: str | None, what: str) -> Path | None:
    """Validate a path given by the user (quotes and environment variables allowed)."""
    if not value:
        return None
    p = Path(os.path.expandvars(value.strip().strip('"').strip("'"))).expanduser()
    if not p.is_file():
        raise ValueError(f"{what} not found: {p}. Ask the user for the full path, e.g. C:\\Users\\Name\\Music\\song.mp3")
    if p.suffix.lower() not in AUDIO_EXT:
        raise ValueError(f"{what} must be an audio file ({', '.join(sorted(AUDIO_EXT))}): {p}")
    return p


def safe_name(name: str | None) -> str | None:
    """File name chosen by the user, made valid on Windows (no extension, no forbidden characters)."""
    if not name:
        return None
    name = name.strip()
    if Path(name).suffix.lower() in AUDIO_EXT:  # "song.mp3" -> "song", but "v1.2 final" stays as it is
        name = name[: -len(Path(name).suffix)]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name)
    name = name.strip(" .")[:80]
    return name or None


# ---------------------------------------------------------------- ACE-Step page API (Gradio)


def _page_open(url: str, path: str, data: bytes | None = None, headers: dict | None = None, timeout: float = 60):
    return _opener.open(urllib.request.Request(url + path, data=data, headers=headers or {}), timeout=timeout)


def page_upload(url: str, path: Path) -> dict:
    """Upload a local file to the page and return the value an Audio input expects."""
    boundary = uuid.uuid4().hex
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{path.name}"\r\n'
            f"Content-Type: {mimetypes.guess_type(path.name)[0] or 'application/octet-stream'}\r\n\r\n").encode()
    body = head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    with _page_open(url, "/gradio_api/upload", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}) as r:
        server_path = json.load(r)[0]
    return {"path": server_path, "orig_name": path.name, "meta": {"_type": "gradio.FileData"}}


def page_call(url: str, api: str, data: list, session: str) -> list:
    """Run a page event in a session and wait for its result (session results arrive on /queue/data)."""
    body = json.dumps({"data": data, "session_hash": session}).encode()
    with _page_open(url, f"/gradio_api/call/{api}", body, {"Content-Type": "application/json"}) as r:
        event_id = json.load(r)["event_id"]
    with _page_open(url, f"/gradio_api/queue/data?session_hash={session}", timeout=HTTP_TIMEOUT) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            msg = json.loads(line[5:])
            if msg.get("event_id") != event_id:
                continue
            if msg.get("msg") == "process_completed":
                out = msg.get("output") or {}
                if not msg.get("success"):
                    raise RuntimeError(f"ACE-Step page error in {api}: {out.get('error') or out}")
                return out.get("data") or []
            if msg.get("msg") == "unexpected_error":
                raise RuntimeError(f"ACE-Step page error in {api}: {msg.get('message')}")
    raise RuntimeError(f"ACE-Step page closed the connection during {api}")


def page_generate(url: str, page_mode: str, overrides: dict) -> list[dict]:
    """Generate through the page's own "generation_wrapper", exactly like the Generate button.
    The inputs are read from the page every time: labelled ones by label (defaults from the page), the internal
    session states (mode etc.) are set by first running the page's mode-change event in the same session."""
    cfg = json.load(_page_open(url, "/config"))
    info = json.load(_page_open(url, "/gradio_api/info"))
    comps = {c["id"]: c for c in cfg.get("components", [])}
    gen_dep = next((d for d in cfg.get("dependencies", []) if d.get("api_name") == "generation_wrapper"), None)
    mode_api = next((d["api_name"] for d in cfg.get("dependencies", [])
                     if str(d.get("api_name") or "").startswith("_handle_mode_change")), None)
    params = (info.get("named_endpoints", {}).get("/generation_wrapper") or {}).get("parameters")
    if not gen_dep or not mode_api or not params:
        raise RuntimeError("This ACE-Step version changed its page: audio-based modes are not available. "
                           "Update Music Studio for ACE-Step.")
    labels = {p["label"] for p in params}
    unknown = [k for k in overrides if k not in labels]
    if unknown:
        raise RuntimeError(f"This ACE-Step version changed its page (missing fields: {', '.join(unknown)}). "
                           "Update Music Studio for ACE-Step.")
    values = {}
    for p in params:
        v = p.get("parameter_default") if p.get("parameter_has_default") else None
        if p["label"] in overrides:
            v = overrides[p["label"]]
            enum = (p.get("type") or {}).get("enum")
            if enum and v not in enum and v is not None:  # e.g. a vocal language the page does not list
                v = p.get("parameter_default")
        values[p["label"]] = v
    session = uuid.uuid4().hex[:12]
    page_call(url, mode_api, [page_mode, "Custom"], session)  # sets the session's task type like the mode radio
    labelled = iter(params)
    data = [None if comps.get(cid, {}).get("type") == "state" else values[next(labelled)["label"]]
            for cid in gen_dep["inputs"]]
    out = page_call(url, "generation_wrapper", data, session)
    files = []
    for item in out[:8]:
        fd = item.get("value") if isinstance(item, dict) and "value" in item else item
        if isinstance(fd, dict) and fd.get("path"):
            files.append(fd["path"])
    if not files:
        status = out[10] if len(out) > 10 else ""
        raise RuntimeError(f"ACE-Step did not return audio. Status: {status}")
    return files


def find_original(page_file: str, outputs_root: str | None) -> Path:
    """The page returns a cached copy: find the original in ACE-Step's gradio_outputs (with its .json details)."""
    name = Path(page_file).name
    if outputs_root and Path(outputs_root).is_dir():
        for d in sorted(Path(outputs_root).glob("batch_*"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
            if (d / name).is_file():
                return d / name
    return Path(page_file)


def audio_seconds(path: Path) -> float | None:
    """Real length of an audio file (ffprobe next to ffmpeg); None if unknown."""
    ffmpeg = find_ffmpeg()
    probe = ffmpeg and str(Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix))
    if not probe or not Path(probe).is_file():
        return None
    r = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        return round(float(r.stdout.strip()), 2)
    except ValueError:
        return None


def song_details(path: Path) -> dict:
    """Metadata ACE-Step writes next to each song (<name>.json)."""
    try:
        d = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"file": str(path), "duration": audio_seconds(path)}
    pick = lambda *k: next((d[x] for x in k if d.get(x) not in (None, "", -1, 0)), None)  # noqa: E731
    return {"file": str(path), "duration": pick("cot_duration", "duration") or audio_seconds(path),
            "bpm": pick("cot_bpm", "bpm"),
            "keyscale": pick("cot_keyscale", "keyscale"), "timesignature": pick("cot_timesignature", "timesignature"),
            "vocal_language": pick("cot_vocal_language", "vocal_language"), "seed": d.get("seed"),
            "caption": pick("cot_caption", "caption"), "lyrics": pick("cot_lyrics", "lyrics")}


# ---------------------------------------------------------------- output files


def finalize_outputs(songs: list[dict], info: dict, file_name: str | None) -> list[dict]:
    """Move every song (with its side files) to <ACE-Step>/gradio_outputs/mcp_<time>[_<name>]/ and give it the
    name chosen by the user: <name>.mp3, <name>_2.mp3, ..."""
    root = info.get("acestep_outputs")
    if not root:
        return songs
    folder = Path(root) / (f"mcp_{datetime.now():%Y%m%d_%H%M%S}" + (f"_{file_name}" if file_name else ""))
    for i, item in enumerate(songs):
        src = Path(item["file"])
        if not src.is_file():
            continue
        new_stem = (file_name if i == 0 else f"{file_name}_{i + 1}") if file_name else src.stem
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for sib in list(src.parent.glob(src.stem + "*")):  # audio + side files (.json, .npz, ...)
                shutil.move(str(sib), str(folder / (new_stem + sib.name[len(src.stem):])))
            item["file"] = str(folder / (new_stem + src.suffix))
            if src.parent.exists() and not any(src.parent.iterdir()):
                src.parent.rmdir()
        except OSError:
            pass  # keep the original path if the move fails
    return songs


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
    """Write a temporary <name>_loop.wav (it then replaces the song, see _run_job): the end is blended (equal power) into the start and the head is cut, so the file's
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


# ---------------------------------------------------------------- generation jobs

_jobs: dict[str, dict] = {}
_gen_lock = threading.Lock()


def _generate_rest(url: str, payload: dict) -> list[dict]:
    res = http_json(url + "/release_task", payload, timeout=HTTP_TIMEOUT)
    task_id = (res.get("data") or {}).get("task_id")
    q = http_json(url + "/query_result", {"task_id_list": [task_id]}, timeout=30)
    return json.loads((q.get("data") or [{}])[0].get("result") or "[]")


def _run_job(job_id: str, url: str, info: dict, request: dict):
    job = _jobs[job_id]
    try:
        with _gen_lock:
            if request["via"] == "rest":
                songs = _generate_rest(url, request["payload"])
            else:
                overrides = dict(request["overrides"])
                for label in ("Source Audio", "Reference Audio"):  # upload the user's files to the page
                    if isinstance(overrides.get(label), Path):
                        overrides[label] = page_upload(url, overrides[label])
                files = page_generate(url, request["page_mode"], overrides)
                songs = [song_details(find_original(f, info.get("acestep_outputs"))) for f in files]
        if not songs:
            raise RuntimeError("ACE-Step returned no audio")
        songs = finalize_outputs(songs, info, request.get("file_name"))
        if request.get("loop_crossfade"):
            for s in songs:  # a loop request delivers ONE file: the loopable <name>.wav replaces the song
                try:
                    original = Path(s["file"])
                    loop = Path(create_loop(str(original), float(s.get("duration") or 30), s.get("bpm"),
                                            s.get("timesignature"), request["loop_crossfade"]))
                    final = original.with_suffix(".wav")
                    original.unlink()
                    loop.replace(final)
                    s.update(file=str(final), looped=True, duration=audio_seconds(final) or s.get("duration"))
                except Exception as e:
                    s["loop_error"] = str(e)  # the normal song is kept
        job.update(status="done", songs=songs)
    except Exception as e:
        job.update(status="error", error=str(e))
    job["seconds"] = round(time.monotonic() - job["started"])


def _job_report(job_id: str) -> dict:
    job = _jobs[job_id]
    out = {"job_id": job_id, "status": job["status"], "mode": job.get("mode")}
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
            **({"seamless_loop": True} if s.get("looped") else {}),
            **({"loop_error": s["loop_error"] + " (the song was kept without the loop)"} if s.get("loop_error") else {}),
        } for s in job["songs"]]
        out["output_folder"] = str(Path(job["songs"][0]["file"]).parent) if job["songs"] else None
        out["next_step"] = ("Tell the user the full path of each file and the output folder; they can also open it "
                            "from the Music Studio app menu 'Open generated songs folder'.")
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
    """Check that ACE-Step is running and return the loaded models, limits (max song length, max variants)
    and the available generation MODES with a one-line description each. Call this first."""
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
        "modes": available_modes(info),
        "ffmpeg_for_loops": bool(find_ffmpeg()),
        "gpu_memory_gb": info.get("gpu_memory_gb"),
        "songs_folder": info.get("acestep_outputs"),
        "generation_running": _gen_lock.locked(),
        "hint": None if reachable else "Ask the user to open the Music Studio for ACE-Step app and wait until the page is visible.",
        "next_step": "Unless the user already named the mode, ask ONLY which mode to use: list every mode with "
                     "available=true and its description (translated), nothing else in that message.",
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
        reference_audio=(str, Field(default="", description="Optional: full path of an audio file whose sound to "
                                                            r"imitate, e.g. C:\Users\Name\Music\song.mp3")),
        duration_seconds=(int, Field(default=0, ge=0, le=limit,
                                     description=f"Approximate length in seconds (max {fmt_length(limit)}); "
                                                 "0 = let ACE-Step choose")),
        loop=(bool, Field(default=False, description="Seamless loop that can repeat forever (games, background)")),
        bpm=(int, Field(default=0, ge=0, le=300, description="Tempo in BPM, 0 = automatic")),
        key=(str, Field(default="", description="Key, e.g. A minor (empty = automatic)")),
        variants=(int, Field(default=1, ge=1, le=max_variants(info), description="How many versions to generate")),
    )


def _questions(mode: str, info: dict) -> list[str]:
    limit = fmt_length(max_duration(info))
    path_q = ("Full path of the {} (paste it, e.g. C:\\Users\\Name\\Music\\song.mp3 — in a terminal you can drag the "
              "file into the window), or should I list your recent songs to choose one?")
    variants = f"How many versions (1-{max_variants(info)})?"
    loop = "Should the result loop seamlessly, like video game background music? (optional)"
    if mode == "simple":
        return ["Describe the song in your own words (style, mood, theme).",
                "Instrumental or with vocals? If vocals, in which language?", variants, loop]
    if mode == "remix":
        return [path_q.format("song to remix"),
                "New style / mood / instruments for the remix?",
                "Keep the original lyrics, change them, or make it instrumental?",
                "How faithful to the original? (0.2 = loose reinterpretation, 0.5 = balanced, 0.8 = faithful cover)",
                variants, loop]
    if mode == "repaint":
        return [path_q.format("song to edit"),
                "Which part to regenerate: from second … to second … (end = until the end)?",
                "What should that part contain (style, instruments, new lyrics for that part)?", variants]
    if mode == "extract":
        return [path_q.format("song"), "Which part to isolate? " + ", ".join(TRACKS)]
    if mode == "lego":
        return [path_q.format("song"), "Which track to add or replace? " + ", ".join(TRACKS),
                "Describe the sound of that track.", "Only in a time range (from … to … seconds) or the whole song?"]
    if mode == "complete":
        return [path_q.format("partial song"), "Which tracks to add? " + ", ".join(TRACKS),
                "Style of the complete arrangement?"]
    return ["Genre / style (e.g. lo-fi, rock, epic orchestral, Italian pop)?",
            "Mood or atmosphere?", "Main instruments (optional)?",
            "Instrumental or with vocals? If vocals: shall I write the lyrics, will you provide them, "
            "or should ACE-Step improvise them?",
            "Language of the lyrics (" + ", ".join(LANGUAGES[:-1]) + ")?",
            "What should the lyrics be about?",
            f"Approximate length? (max {limit}) — or should ACE-Step choose it?",
            "Optional reference audio to imitate its sound: " + path_q.format("reference audio file"),
            "Tempo (BPM) and key, or automatic?", variants, loop]


@mcp.tool()
async def acestep_ask_song_details(
    ctx: Context,
    mode: Literal["simple", "custom", "remix", "repaint", "extract", "lego", "complete"] = "custom",
    idea: str = "",
) -> dict:
    """Return the questions to ask the user for the chosen mode (a form is shown for Custom in clients that
    support MCP elicitation). `idea` = what the user already said. Ask the file name last, before generating."""
    info = server_info()
    if mode == "custom":
        caps = ctx.client_capabilities
        if caps is not None and getattr(caps, "elicitation", None) is not None:
            try:
                res = await ctx.elicit(
                    message=("Describe the song to generate" + (f" (idea: {idea})" if idea else "")
                             + ". Leave optional fields empty to let ACE-Step decide."),
                    schema=_details_model(info))
                if isinstance(res, AcceptedElicitation):
                    return {"mode": mode, "answers": res.data.model_dump(),
                            "ask_last": "File name for the song (without extension)?",
                            "next_step": "Write caption and lyrics from these answers, show the summary table, ask "
                                         "for confirmation, ask the file name, then call acestep_generate."}
                return {"answers": None, "user_action": res.action,
                        "next_step": "The user closed the form: ask in the chat what they want instead."}
            except Exception:
                pass  # fall back to questions in the chat
    return {
        "mode": mode,
        "mode_description": MODES[mode][4],
        "ask_the_user": _questions(mode, info),
        "ask_last": "File name for the song (without extension)? Suggest one from the description.",
        "how_to_ask": "Ask only what is still unknown, in the user's language, as a short numbered list or a small "
                      "table with suggested defaults. Do NOT ask the file name now. Then show a summary and ask for "
                      "confirmation; only after the confirmation ask the file name (ask_last) in its own message.",
        "idea_so_far": idea,
    }


@mcp.tool()
async def acestep_generate(
    ctx: Context,
    caption: str = "",
    mode: Literal["simple", "custom", "remix", "repaint", "extract", "lego", "complete"] = "custom",
    lyrics: str = "",
    instrumental: bool = False,
    file_name: Optional[str] = None,
    source_audio: Optional[str] = None,
    reference_audio: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    repaint_start: Optional[float] = None,
    repaint_end: Optional[float] = None,
    remix_strength: float = 0.5,
    melody_retention: float = 0.2,
    track: Optional[str] = None,
    tracks: Optional[list[str]] = None,
    bpm: Optional[int] = None,
    key: Optional[str] = None,
    time_signature: Optional[Literal["2", "3", "4", "6"]] = None,
    vocal_language: str = "en",
    variants: int = 1,
    audio_format: Literal["mp3", "flac", "wav"] = "mp3",
    seed: Optional[int] = None,
    make_loop: bool = False,
    loop_crossfade_seconds: float = 2.0,
    let_acestep_write: bool = False,
) -> dict:
    """Generate music with ACE-Step. Confirm the details with the user and ask the file name first.

    mode: simple (caption = free description, ACE-Step writes everything), custom (caption = English style tags,
      lyrics, optional reference_audio), remix (source_audio + new caption; remix_strength 0-1 = how faithful,
      melody_retention 0-1), repaint (source_audio + repaint_start/repaint_end seconds, -1 = end; caption/lyrics
      for that part), extract (source_audio + track), lego (source_audio + track + caption, optional range),
      complete (source_audio + tracks + caption). extract/lego/complete need a base model.
    source_audio / reference_audio: full paths of audio files on this PC (pasted by the user or from
      acestep_list_songs).
    lyrics: lyrics with [Verse]/[Chorus]/... tags in `vocal_language`; leave empty if instrumental.
    duration_seconds: length for simple/custom (see acestep_status for the maximum); omit to let ACE-Step decide.
    file_name: name chosen by the user, without extension. One song = one file <name>.mp3; only when the user
      asks for more versions (variants) the others are <name>_2.mp3, <name>_3.mp3, ...
    make_loop: deliver the song as a single <name>.wav that repeats seamlessly (needs ffmpeg).
    Returns the file path(s) and folder, or a job_id to pass to acestep_get_result if it takes longer.
    """
    info, url = check_server()
    if let_acestep_write:
        mode = "simple"
    if _gen_lock.locked():
        running = [j for j, v in _jobs.items() if v["status"] == "running"]
        return {"error": "Another song is being generated.", "running_job_id": running[0] if running else None}
    page_mode, task, needs_source, base_only, _ = MODES[mode]
    if base_only and not is_base_model(info):
        return {"error": f"Mode {page_mode} needs an ACE-Step base model; the loaded model is "
                         f"{info.get('dit_model')}. Available modes: simple, custom, remix, repaint."}
    limit = max_duration(info)
    try:
        src = audio_path(source_audio, "Source audio")
        ref = audio_path(reference_audio, "Reference audio")
    except ValueError as e:
        return {"error": str(e)}
    if needs_source and not src:
        return {"error": f"Mode {page_mode} needs source_audio: ask the user for the full path of the song "
                         "(e.g. C:\\Users\\Name\\Music\\song.mp3) or offer acestep_list_songs."}
    if duration_seconds is not None and not 10 <= duration_seconds <= limit:
        return {"error": f"duration_seconds must be between 10 and {limit} with the loaded models."}
    if not 1 <= variants <= max_variants(info):
        return {"error": f"variants must be between 1 and {max_variants(info)}."}
    if bpm is not None and not 30 <= bpm <= 300:
        return {"error": "bpm must be between 30 and 300."}
    if vocal_language not in LANGUAGES:
        return {"error": "vocal_language must be one of: " + ", ".join(LANGUAGES)}
    if not 0 <= remix_strength <= 1 or not 0 <= melody_retention <= 1:
        return {"error": "remix_strength and melody_retention must be between 0 and 1."}
    if mode in ("extract", "lego") and track not in TRACKS:
        return {"error": "track must be one of: " + ", ".join(TRACKS)}
    if mode == "complete" and (not tracks or any(t not in TRACKS for t in tracks)):
        return {"error": "tracks must be a list of: " + ", ".join(TRACKS)}
    if mode == "repaint" and repaint_start is None:
        return {"error": "repaint needs repaint_start (and repaint_end, -1 = until the end)."}
    if mode not in ("extract",) and not caption.strip():
        return {"error": "caption is required."}
    if make_loop and not 0.5 <= loop_crossfade_seconds <= 8:
        return {"error": "loop_crossfade_seconds must be between 0.5 and 8."}
    if make_loop and not find_ffmpeg():
        return {"error": "make_loop needs ffmpeg: ask the user to install it (winget install Gyan.FFmpeg)."}

    sung = "[Instrumental]" if instrumental or not lyrics.strip() else lyrics
    request = {"file_name": safe_name(file_name), "loop_crossfade": loop_crossfade_seconds if make_loop else None}
    if mode == "simple" or (mode == "custom" and not ref):
        payload = {"batch_size": variants, "audio_format": audio_format, "vocal_language": vocal_language,
                   "thinking": bool(info.get("lm_model", True)), "use_random_seed": seed is None}
        if seed is not None:
            payload["seed"] = seed
        if mode == "simple":
            payload["sample_query"] = caption + (" (instrumental)" if instrumental else "")
        else:
            payload.update(prompt=caption, lyrics=sung)
            for k, v in (("audio_duration", duration_seconds), ("bpm", bpm), ("key_scale", key),
                         ("time_signature", time_signature)):
                if v:
                    payload[k] = v
        request.update(via="rest", payload=payload)
    else:
        ov = {"Music Caption": caption or track or "", "Lyrics": sung, "Vocal Language": vocal_language,
              "Batch Size": variants, "Audio Format": audio_format, "Random Seed": seed is None,
              "Seed": str(seed) if seed is not None else "-1",
              "Audio Duration (seconds)": duration_seconds if (duration_seconds and mode == "custom") else -1,
              "BPM (Beats Per Minute)": bpm, "Key": key or "", "Time Signature": time_signature or "",
              "Think": bool(info.get("lm_model")) and task == "text2music",
              "AutoGen": False, "Auto Score": False, "Auto LRC": False, "LM Codes Hints": "",
              "source caption": "", "source lyrics": ""}
        if task in INSTRUCTION:
            ov["Instruction"] = INSTRUCTION[task]
        elif task == "extract":
            ov["Instruction"] = f"Extract the {track.upper()} track from the audio:"
        elif task == "lego":
            ov["Instruction"] = f"Generate the {track.upper()} track based on the audio context:"
        elif task == "complete":
            ov["Instruction"] = f"Complete the input track with {' | '.join(t.upper() for t in tracks)}:"
        if ref:
            ov["Reference Audio"] = ref
        if src:
            ov["Source Audio"] = src
        if mode == "remix":
            ov["LM Codes Strength"] = remix_strength
            ov["Cover Strength (Melody Retention)"] = melody_retention
        if mode in ("repaint", "lego") and repaint_start is not None:
            ov["Repainting Start"] = repaint_start
            ov["Repainting End"] = repaint_end if repaint_end is not None else -1
        if mode in ("extract", "lego"):
            ov["Track Name"] = track
        if mode == "complete":
            ov["Track Names"] = tracks
        request.update(via="page", page_mode=page_mode, overrides=ov)

    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {"status": "running", "started": time.monotonic(), "mode": mode}
    threading.Thread(target=_run_job, args=(job_id, url, info, request), daemon=True).start()
    return await _wait(job_id, WAIT_SECONDS, ctx)


@mcp.tool()
async def acestep_get_result(ctx: Context, job_id: str, wait_seconds: int = WAIT_SECONDS) -> dict:
    """Wait for a generation started by acestep_generate and return the song file path(s) and folder."""
    if job_id not in _jobs:
        return {"error": f"Unknown job_id {job_id} (jobs are lost if the MCP server restarts)."}
    return await _wait(job_id, max(0, min(wait_seconds, WAIT_SECONDS)), ctx)


@mcp.tool()
def acestep_list_songs(limit: int = 10) -> dict:
    """List the most recent songs in ACE-Step's output folder (newest first): useful to pick a source song
    for Remix/Repaint."""
    folder = server_info().get("acestep_outputs")
    if not folder or not os.path.isdir(folder):
        return {"error": "Songs folder unknown: open the Music Studio for ACE-Step app once."}
    files = [p for p in Path(folder).rglob("*") if p.suffix.lower() in AUDIO_EXT]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return {"folder": folder, "songs": [
        {"file": str(p), "name": p.name,
         "created": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")}
        for p in files[:max(1, min(limit, 100))]]}


@mcp.prompt(title="Compose a song with Music Studio for ACE-Step")
def compose_song(idea: str = "") -> str:
    """Guided interview to create a song with ACE-Step."""
    return ("Help me create music with ACE-Step. " + (f"My idea: {idea}. " if idea else "")
            + "Follow the Music Studio flow: check acestep_status, ask me which mode to use (explain each one in a "
              "line), collect the details for that mode with acestep_ask_song_details (ask me in my language; show "
              "the maximum length in brackets; for audio files ask me to paste the full path), show me a summary "
              "table and wait for my confirmation, ask the file name as the last question, then generate with "
              "acestep_generate and tell me where the files are.")


if __name__ == "__main__":
    mcp.run("stdio")
