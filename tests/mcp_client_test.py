"""End-to-end test of mcp/music_studio_mcp.py over stdio, like an AI client would use it.

Usage: uv run --no-project --with "mcp>=2.3,<3" python tests/mcp_client_test.py [--generate] [--loop] [--form] [--dist]
  --generate  really generate a 15 s instrumental (the Music Studio app must be open)
  --loop      really generate a loopable track and check that the _loop.wav joins seamlessly
  --form      advertise elicitation support and auto-fill the form
  --dist      use the copy shipped next to the exe (dist\\Music Studio\\mcp)
"""

import array
import asyncio
import json
import sys
import wave
from pathlib import Path

from mcp import types
from mcp.client import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
SERVER = (ROOT / "dist" / "Music Studio" / "mcp" if "--dist" in sys.argv else ROOT / "mcp") / "music_studio_mcp.py"


async def on_elicit(context, params):
    print("FORM:", params.message)
    print("FORM FIELDS:", list(params.requested_schema.get("properties", {})))
    return types.ElicitResult(action="accept", content={
        "style": "lo-fi hip hop", "mood": "relaxed", "instruments": "piano, soft drums",
        "vocals": "instrumental", "vocal_language": "en", "lyrics_topic": "", "duration_seconds": 15,
        "loop": False, "bpm": 80, "key": "", "variants": 1})


def show(name, res):
    text = "".join(c.text for c in res.content if getattr(c, "type", "") == "text")
    print(f"--- {name} (error={res.is_error}):\n{text[:1500]}")
    return json.loads(text) if text.startswith("{") else text


async def generate(s, args):
    res = show("generate", await s.call_tool("acestep_generate", args))
    while isinstance(res, dict) and res.get("status") == "running":
        res = show("get_result", await s.call_tool("acestep_get_result", {"job_id": res["job_id"]}))
    assert res["status"] == "done", res
    return res["songs"][0]


def seam_check(path):
    """Jump between the last and the first sample vs. the typical sample-to-sample step."""
    with wave.open(path) as w:
        ch, n, rate = w.getnchannels(), w.getnframes(), w.getframerate()
        data = array.array("h", w.readframes(n))
    left = data[0::ch]
    steps = sorted(abs(left[i + 1] - left[i]) for i in range(0, len(left) - 1, 7))
    p99 = steps[int(len(steps) * 0.99)]
    jump = abs(left[0] - left[-1])
    print(f"loop: {n / rate:.2f} s, seam jump {jump}, 99th percentile step {p99}")
    assert jump <= p99, "audible click at the loop point"
    return n / rate


async def main():
    params = StdioServerParameters(command="uv", args=["run", "--script", str(SERVER)])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w, elicitation_callback=on_elicit if "--form" in sys.argv else None) as s:
            init = await s.initialize()
            print("server:", init.server_info.name, "| instructions:", bool(init.instructions))
            print("tools:", [t.name for t in (await s.list_tools()).tools])
            print("prompts:", [p.name for p in (await s.list_prompts()).prompts])
            show("status", await s.call_tool("acestep_status", {}))
            show("ask", await s.call_tool("acestep_ask_song_details", {"idea": "relaxing study music"}))
            show("bad duration", await s.call_tool("acestep_generate", {"caption": "x", "duration_seconds": 5}))
            show("list", await s.call_tool("acestep_list_songs", {"limit": 3}))
            if "--generate" in sys.argv:
                song = await generate(s, {"caption": "lo-fi hip hop, relaxed, warm piano, soft drums, vinyl crackle",
                                          "instrumental": True, "duration_seconds": 15, "bpm": 80})
                f = Path(song["file"])
                assert f.is_file() and "gradio_outputs" in str(f), f
                print("OK file:", f, f.stat().st_size)
            if "--loop" in sys.argv:
                song = await generate(s, {
                    "caption": "chiptune video game level music, upbeat, seamless loop, loopable, steady energy, "
                               "no intro, no outro, no fade in, no fade out",
                    "instrumental": True, "duration_seconds": 24, "bpm": 120, "time_signature": "4",
                    "make_loop": True})
                assert song.get("loop_file"), song
                length = seam_check(song["loop_file"])
                assert abs(length / 2.0 - round(length / 2.0)) < 0.02, "loop is not a whole number of bars"
                print("OK loop:", song["loop_file"])


asyncio.run(main())
