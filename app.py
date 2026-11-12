"""Music Studio for ACE-Step: native window (pywebview + WebView2) for the ACE-Step 1.5 Gradio UI.

The app does not contain ACE-Step: it runs `uv run acestep` in the folder set in config.json.
"""

import base64
import collections
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime
from logging.handlers import RotatingFileHandler

import webview
from webview.menu import Menu, MenuAction, MenuSeparator

import i18n
import winsys
from i18n import t
from version import VERSION

APP_TITLE = "Music Studio for ACE-Step"
FROZEN = getattr(sys, "frozen", False)
APP_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
ICON_ICO = os.path.join(RES_DIR, "assets", "icon.ico")
ICON_PNG = os.path.join(RES_DIR, "assets", "icon.png")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
INFO_PATH = os.path.join(APP_DIR, "server_info.json")  # read by the MCP server (mcp/)
LOG_DIR = os.path.join(APP_DIR, "logs")
SERVER_LOG = os.path.join(LOG_DIR, "server.log")
UPDATES_LOG = os.path.join(LOG_DIR, "updates.log")
STALL_SECONDS = 600  # error only if the server prints nothing and does not answer for 10 minutes
HEAD_CHECK_SECONDS = 60
MODELS_POLL_SECONDS = 15

DEFAULTS = {
    "acestep_path": os.path.expanduser(r"~\ACE-Step-1.5"),
    "port": 7860,
    "window_width": 1280,
    "window_height": 800,
    "language": "auto",
    "enable_api": True,
    "skip_version": "",
}

MENU_KEYS = ["menu_updates", "menu_open_songs", "menu_log", "menu_restart", "menu_language",
             "lang_auto", "lang_en", "lang_it", "lang_acestep"]

log = logging.getLogger("app")
srvlog = logging.getLogger("server")


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    for logger, name, fmt in ((log, "app.log", "%(asctime)s %(levelname)s %(message)s"),
                              (srvlog, "server.log", "%(asctime)s %(message)s")):
        h = RotatingFileHandler(os.path.join(LOG_DIR, name), maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def load_config():
    """Return (config, error message key args). Creates config.json with defaults if missing."""
    cfg = dict(DEFAULTS)
    if not os.path.exists(CONFIG_PATH):
        save_config(cfg)
        return cfg, None
    try:
        with open(CONFIG_PATH, encoding="utf-8-sig") as f:  # also accept files saved with a BOM
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
        cfg.update(data)
        for k in ("port", "window_width", "window_height"):
            cfg[k] = int(cfg[k])
        if not 1 <= cfg["port"] <= 65535:
            raise ValueError("port must be between 1 and 65535")
    except Exception as e:
        return dict(DEFAULTS), str(e)
    return cfg, None


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def fmt_seconds(s):
    return f"{s // 60} min" if s % 60 == 0 else f"{s // 60}:{s % 60:02d}"


def _icon_data_uri():
    try:
        with open(ICON_PNG, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    except OSError:
        return ""


LOADING_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Music Studio for ACE-Step</title><style>
:root{color-scheme:dark}
body{margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
 background:#15131f;color:#ebe8f5;font:15px "Segoe UI",system-ui,sans-serif;padding:0 16px;box-sizing:border-box}
img{width:88px;height:88px}
h1{font-size:22px;font-weight:600;margin:16px 0 6px;text-align:center}
#s{color:#aaa4c8;margin-bottom:14px;min-height:20px;text-align:center}
#e{display:none;max-width:760px;white-space:pre-wrap;background:#3a1620;border:1px solid #7a2a3c;color:#ffd6de;
 border-radius:8px;padding:12px 14px;margin-bottom:12px}
#a{display:none;gap:10px;margin-bottom:14px;flex-wrap:wrap;justify-content:center}
button{background:#6d5df6;color:#fff;border:0;border-radius:6px;padding:8px 16px;font:inherit;cursor:pointer}
button.sec{background:#2d2a40}
pre{width:min(900px,92vw);height:38vh;overflow:auto;background:#0c0b13;border:1px solid #2b2840;border-radius:8px;
 padding:10px 12px;font:12px Consolas,monospace;color:#bdb8d6;white-space:pre-wrap;margin:0;box-sizing:border-box}
.dots::after{content:'';animation:d 1.5s steps(4) infinite}@keyframes d{0%{content:''}25%{content:'.'}50%{content:'..'}75%{content:'...'}}
</style></head><body>
<img src="{ICON}" alt="">
<h1 id="t"></h1>
<div id="s" class="dots"></div>
<div id="e"></div>
<div id="a"><button id="bc" style="display:none" onclick="pywebview.api.choose_acestep()"></button>
<button id="br" onclick="pywebview.api.retry()"></button><button id="bl" class="sec" onclick="pywebview.api.open_log()"></button></div>
<pre id="l"></pre>
<div style="position:fixed;right:14px;bottom:10px;color:#6b6585;font-size:12px">Music Studio for ACE-Step {VERSION}</div>
<script>
const $=id=>document.getElementById(id);
function setLabels(r,l,c){$('br').textContent=r;$('bl').textContent=l;$('bc').textContent=c}
function setStatus(t,s){$('t').textContent=t;$('s').textContent=s;$('s').className='dots';$('e').style.display='none';$('a').style.display='none'}
function setLog(t){const l=$('l');l.textContent=t;l.scrollTop=l.scrollHeight}
function showError(t,m,c){$('t').textContent=t;$('s').textContent='';$('s').className='';$('e').textContent=m;$('e').style.display='block';$('a').style.display='flex';$('bc').style.display=c?'':'none'}
</script></body></html>""".replace("{VERSION}", VERSION)

# Injected into the Gradio page: discreet banners and the app's dialogs.
OVERLAY_JS = r"""
(function(){
 if (window.aceApp && document.getElementById('ace-app-root')) return;
 const root=document.createElement('div'); root.id='ace-app-root';
 root.style.cssText='position:fixed;top:10px;right:10px;z-index:2147483646;display:flex;flex-direction:column;gap:8px;max-width:460px;font:14px "Segoe UI",system-ui,sans-serif';
 document.body.appendChild(root);
 const act=(k,v)=>{window.aceApp.hide(k); if(window.pywebview&&window.pywebview.api) window.pywebview.api.banner_action(k,v);};
 window.aceApp={
  show(b){
   this.hide(b.key);
   const colors={note:'#2d2a40',info:'#1f3a5f',warn:'#5a3a12',update:'#3b2f7a',modal:'#24213a'};
   const box=document.createElement('div'); box.id='ace-b-'+b.key;
   box.style.cssText='background:'+(colors[b.kind]||'#2d2a40')+';color:#f2f0fa;border-radius:10px;padding:12px 14px;box-shadow:0 6px 24px rgba(0,0,0,.35);line-height:1.4';
   if(b.title){const h=document.createElement('div');h.style.cssText='font-weight:600;margin-bottom:4px;padding-right:18px';h.textContent=b.title;box.appendChild(h);}
   if(b.text){const p=document.createElement('div');p.style.whiteSpace='pre-wrap';p.textContent=b.text;box.appendChild(p);}
   if(b.items&&b.items.length){const u=document.createElement('ul');u.style.cssText='margin:6px 0 0 0;padding-left:18px;font-size:13px;opacity:.9';
     b.items.forEach(i=>{const li=document.createElement('li');li.textContent=i;u.appendChild(li);});box.appendChild(u);}
   if(b.buttons&&b.buttons.length){const r=document.createElement('div');r.style.cssText='display:flex;gap:8px;flex-wrap:wrap;margin-top:10px';
     b.buttons.forEach(x=>{const bt=document.createElement('button');bt.textContent=x[0];
      bt.style.cssText='border:0;border-radius:6px;padding:6px 12px;cursor:pointer;font:inherit;color:#fff;background:'+(x[2]?'#7c6cff':'rgba(255,255,255,.14)');
      bt.onclick=()=>act(b.key,x[1]);r.appendChild(bt);});box.appendChild(r);}
   if(b.closable){const c=document.createElement('button');c.textContent='×';c.title=b.close_label||'';
     c.style.cssText='position:absolute;top:6px;right:8px;border:0;background:none;color:#fff;font-size:18px;cursor:pointer;opacity:.7';
     c.onclick=()=>act(b.key,'close');box.style.position='relative';box.style.paddingRight='34px';box.appendChild(c);}
   if(b.kind==='modal'){
     const bg=document.createElement('div');bg.id='ace-b-'+b.key;
     bg.style.cssText='position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;padding:16px';
     box.id='';box.style.maxWidth='520px';bg.appendChild(box);document.body.appendChild(bg);
   } else { root.appendChild(box); }
  },
  hide(k){const e=document.getElementById('ace-b-'+k); if(e) e.remove();},
  progress(s){  // floating card in the middle of the window while a song is generated
   let c=document.getElementById('ace-progress');
   if(!s.active){ if(c) c.remove(); return; }
   if(!c){
     c=document.createElement('div'); c.id='ace-progress';
     c.style.cssText='position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:2147483645;width:min(460px,86vw);'
       +'background:rgba(28,25,46,.94);color:#f2f0fa;border-radius:14px;padding:18px 20px;box-shadow:0 12px 40px rgba(0,0,0,.45);'
       +'font:14px "Segoe UI",system-ui,sans-serif;pointer-events:none';
     c.innerHTML='<div class="t" style="margin-bottom:12px;line-height:1.35"></div>'
       +'<div style="display:flex;align-items:center;gap:12px"><div style="flex:1;height:10px;border-radius:5px;background:rgba(255,255,255,.14);overflow:hidden">'
       +'<div class="b" style="height:100%;width:0;border-radius:5px;background:linear-gradient(90deg,#8b5cf6,#2563eb);transition:width .6s ease"></div></div>'
       +'<div class="p" style="min-width:42px;text-align:right;font-weight:600"></div></div>';
     document.body.appendChild(c);
   }
   c.querySelector('.t').textContent=s.text; c.querySelector('.b').style.width=s.pct+'%'; c.querySelector('.p').textContent=s.pct+'%';
  }
 };
})();
"""

# Lines printed by ACE-Step at start (GPU config block, CLI model init)
INFO_PATTERNS = [
    ("gpu_memory_gb", re.compile(r"GPU Memory: ([\d.]+) GB"), float),
    ("tier", re.compile(r"Configuration Tier: (\S+)"), str),
    ("max_duration_with_lm", re.compile(r"Max Duration \(with LM\): (\d+)s"), int),
    ("max_duration_without_lm", re.compile(r"Max Duration \(without LM\): (\d+)s"), int),
    ("max_batch_with_lm", re.compile(r"Max Batch Size \(with LM\): (\d+)"), int),
    ("max_batch_without_lm", re.compile(r"Max Batch Size \(without LM\): (\d+)"), int),
    ("dit_model", re.compile(r"Initializing DiT model: (\S+)"), str),
    ("lm_model", re.compile(r"Initializing 5Hz LM: (\S+)"), str),
]


# Generation milestones printed by ACE-Step (UI and API): (pattern, progress %, i18n key of the phase)
PROGRESS_STEPS = [
    (re.compile(r"LLM usage decision|Phase 1: Generating CoT"), 5, "gen_plan"),
    (re.compile(r"Phase 2: Generating audio codes"), 25, "gen_compose"),
    (re.compile(r"\[generate_music\] Starting generation"), 45, "gen_prepare"),
    (re.compile(r"\[service_generate\] Generating audio"), 65, "gen_audio"),
    (re.compile(r"Decoding latents with VAE"), 80, "gen_decode"),
    (re.compile(r"VAE decode completed"), 92, "gen_save"),
]
PROGRESS_DECODE = re.compile(r"Decoding audio chunks:\s+(\d+)%")  # real tqdm percentage of the VAE decode
PROGRESS_DONE = re.compile(r"\[AudioSaver\] Saved audio")


class AppError(Exception):
    pass


class Server:
    """ACE-Step server managed by the app, inside a Job Object (it dies with the app)."""

    def __init__(self, app):
        self.app = app
        self.job = None
        self.proc = None
        self.last_output = time.monotonic()

    def start(self):
        app = self.app
        env = winsys.build_env()
        uv = winsys.which("uv", env)
        if not uv:
            raise AppError(t("uv_missing"))
        ffmpeg = winsys.which("ffmpeg", env)
        cmd = [uv, "run", "acestep", "--port", str(app.port)]
        if app.cfg.get("enable_api"):
            cmd.append("--enable-api")
        srvlog.info("=== Starting server: %s (folder %s) ===", " ".join(cmd), app.repo)
        srvlog.info("uv: %s | ffmpeg: %s", uv, ffmpeg or "NOT FOUND")
        log.info("Starting server: %s | ffmpeg: %s", cmd, ffmpeg)
        self.job = winsys.Job()
        self.proc = self.job.spawn(cmd, app.repo, env)
        self.last_output = time.monotonic()
        threading.Thread(target=winsys.read_lines, args=(self.proc.stdout, self._on_line), daemon=True).start()
        return ffmpeg

    def _on_line(self, line, partial):
        self.last_output = time.monotonic()
        self.app.console_feed(line, partial)
        self.app.on_progress_line(line)
        if not partial and line.strip():
            srvlog.info(line)
            self.app.parse_server_line(line)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if not self.job:
            return
        log.info("Stopping server (PID %s)", self.proc.pid if self.proc else "?")
        self.job.terminate()
        try:
            self.proc.wait(15)
        except Exception:
            pass
        self.job.close()
        self.job = None
        self.app.reset_progress()
        freed = winsys.wait_port_free(self.app.port)
        log.info("Server stopped; port %s %s", self.app.port, "free" if freed else "STILL IN USE")
        srvlog.info("=== Server stopped ===")


class Api:
    """Functions callable from the pages (window.pywebview.api). No attributes on purpose:
    pywebview would expose nested objects too."""

    def banner_action(self, key, value):
        threading.Thread(target=APP.banner_action, args=(key, value), daemon=True).start()

    def retry(self):
        threading.Thread(target=APP.boot, daemon=True).start()

    def open_log(self):
        APP.open_log()

    def choose_acestep(self):
        threading.Thread(target=APP.choose_acestep, daemon=True).start()


class App:
    def __init__(self, cfg, cfg_error):
        self.cfg = cfg
        self.cfg_error = cfg_error
        self.repo = os.path.abspath(os.path.expandvars(cfg["acestep_path"]))
        self.port = cfg["port"]
        self.url = f"http://127.0.0.1:{self.port}/"
        self.env = winsys.build_env()
        self.git_exe = winsys.which("git", self.env)
        self.uv_exe = winsys.which("uv", self.env)
        self.server = Server(self)
        self.window = None
        self.strip = None  # native WinForms MenuStrip
        self.mode = None  # "managed" | "external"
        self.page = "loading"
        self.loaded = threading.Event()
        self.busy = threading.Lock()
        self.head_lock = threading.Lock()
        self.confirm_lock = threading.Lock()
        self.console = collections.deque(maxlen=400)
        self.console_partial = ""
        self.banners = {}
        self.server_info = {}
        self.start_head = None
        self.dismissed_head = None
        self.changed_head = None
        self.anomaly_logged = None
        self.pending_update = None
        self.closing = False
        self.monitor_started = False
        self.native_ready = False
        self.update_checked = False
        self.icon_uri = _icon_data_uri()
        self.gen ={"active": False, "pct": 0, "phase": "", "t0": 0.0, "done_at": 0.0}
        self.gen_lock = threading.Lock()

    # ---------- page ----------

    def js(self, script):
        try:
            return self.window.evaluate_js(script)
        except Exception as e:
            log.debug("evaluate_js failed: %s", e)

    def on_loaded(self):
        self.loaded.set()
        if self.page == "app":
            self.js(OVERLAY_JS)
            for b in list(self.banners.values()):
                self.js(f"window.aceApp&&window.aceApp.show({json.dumps(b)})")
            self.update_progress()
            threading.Thread(target=self.poll_acestep_language, daemon=True).start()
        else:
            self.js(f"setLabels({json.dumps(t('retry'))},{json.dumps(t('open_log'))},{json.dumps(t('choose_acestep'))})")

    def show_loading(self, title, status=""):
        if self.page != "loading":
            self.page = "loading"
            self.loaded.clear()
            self.window.load_html(LOADING_HTML.replace("{ICON}", self.icon_uri))
            self.loaded.wait(15)
        self.js(f"setStatus({json.dumps(title)},{json.dumps(status)})")

    def show_error(self, title, message, choose=False):
        log.error("%s: %s", title, message)
        self.show_loading(title)
        self.js(f"showError({json.dumps(title)},{json.dumps(message)},{json.dumps(choose)})")
        self.push_console()

    def show_app(self):
        self.page = "app"
        self.loaded.clear()
        self.window.load_url(self.url)

    def console_feed(self, line, partial):
        if partial:
            self.console_partial = line
        else:
            self.console_partial = ""
            self.console.append(line)

    def push_console(self):
        if self.page == "loading":
            text = "\n".join(list(self.console)[-18:] + ([self.console_partial] if self.console_partial else []))
            self.js(f"setLog({json.dumps(text)})")

    def show_banner(self, b):
        b.setdefault("close_label", t("close"))
        self.banners[b["key"]] = b
        if self.page == "app":
            self.js(OVERLAY_JS)
            self.js(f"window.aceApp&&window.aceApp.show({json.dumps(b)})")

    def hide_banner(self, key):
        self.banners.pop(key, None)
        if self.page == "app":
            self.js(f"window.aceApp&&window.aceApp.hide({json.dumps(key)})")

    def info(self, text, title="", kind="info", key=None):
        self.show_banner({"key": key or f"info{time.monotonic_ns()}", "kind": kind, "title": title,
                          "text": text, "closable": True})

    # ---------- native menu (WinForms) ----------

    def ui(self, fn):
        """Run fn on the WinForms UI thread."""
        try:
            from System import Action

            self.window.native.Invoke(Action(fn))
        except Exception as e:
            log.warning("UI call failed: %s", e)

    def setup_native(self):
        """Tag menu items with stable names, enlarge the menu font, add the model info label."""
        if self.native_ready:
            return
        self.native_ready = True
        try:
            self.window.native.Activated += lambda s, e: threading.Thread(target=self.check_head, daemon=True).start()
        except Exception as e:
            log.warning("Cannot hook the activation event: %s", e)

        def apply():
            from System.Drawing import Color, Font
            from System.Windows.Forms import ToolStripItemAlignment, ToolStripLabel

            strip = next(c for c in self.window.native.Controls if c.GetType().Name == "MenuStrip")
            strip.Font = Font("Segoe UI", 10.5)
            by_text = {t(k): k for k in MENU_KEYS}

            def walk(items):
                for it in items:
                    if it.Text in by_text:
                        it.Name = by_text[it.Text]
                    if hasattr(it, "DropDownItems"):
                        walk(it.DropDownItems)

            walk(strip.Items)
            label = ToolStripLabel("")
            label.Name = "info"
            label.Alignment = ToolStripItemAlignment.Right
            label.ForeColor = Color.FromArgb(105, 105, 120)
            strip.Items.Add(label)
            self.strip = strip

        self.ui(apply)
        self.retext()

    def _items(self, key):
        return list(self.strip.Items.Find(key, True)) if self.strip else []

    def set_menu_enabled(self, keys, enabled):
        def apply():
            for k in keys:
                for it in self._items(k):
                    it.Enabled = enabled

        self.ui(apply)

    def retext(self):
        pref = self.cfg.get("language", "auto")

        def apply():
            for k in MENU_KEYS:
                for it in self._items(k):
                    it.Text = t(k)
            for k, v in (("lang_auto", "auto"), ("lang_en", "en"), ("lang_it", "it"), ("lang_acestep", "acestep")):
                for it in self._items(k):
                    it.Checked = (pref == v) or (k == "lang_auto" and pref not in ("en", "it", "acestep"))

        self.ui(apply)
        self.update_info_label()

    def update_info_label(self):
        si = self.server_info
        parts = []
        if si.get("dit_model"):
            parts.append(si["dit_model"])
        if si.get("lm_model"):
            parts.append("LM " + si["lm_model"].replace("acestep-5Hz-lm-", ""))
        # ACE-Step allows shorter songs when the language model is loaded: show the limit that applies
        limit = si.get("max_duration_with_lm") if si.get("lm_model") else si.get("max_duration_without_lm")
        if limit:
            parts.append(t("info_max", d=fmt_seconds(limit)))
        text = "  ·  ".join(parts)
        tip = t("info_tip", gpu=si.get("gpu_memory_gb", "?"), tier=si.get("tier", "?"),
                dit=si.get("dit_model", "?"), lm=si.get("lm_model", "?"),
                with_lm=fmt_seconds(si["max_duration_with_lm"]) if si.get("max_duration_with_lm") else "?",
                without=fmt_seconds(si["max_duration_without_lm"]) if si.get("max_duration_without_lm") else "?",
                api=t("api_on") if si.get("api_enabled") else t("api_off")) + f"\n\nMusic Studio for ACE-Step {VERSION}"

        def apply():
            for it in self._items("info"):
                it.Text = text
                it.ToolTipText = tip

        self.ui(apply)

    def acestep_language_labels(self):
        """Label of ACE-Step's "UI Language" dropdown in every language it ships (from its translation files)."""
        labels = {"UI Language"}
        folder = os.path.join(self.repo, "acestep", "ui", "gradio", "i18n")
        try:
            for f in os.listdir(folder):
                if f.endswith(".json"):
                    with open(os.path.join(folder, f), encoding="utf-8") as fh:
                        label = (json.load(fh).get("service") or {}).get("language_label")
                    if label:
                        labels.add(label)
        except (OSError, ValueError):
            pass
        return labels

    def poll_acestep_language(self):
        """Language of ACE-Step's interface (fixed when ACE-Step builds the page: LANGUAGE in its .env or
        --language), read from the page's Gradio config; with "Same as ACE-Step" the app follows it."""
        js = ("(()=>{const L=%s;const c=((window.gradio_config||{}).components||[]).find(x=>x.props&&"
              "L.includes(x.props.label));return c?c.props.value:null;})()" % json.dumps(sorted(self.acestep_language_labels())))
        code = self.js(js)
        if isinstance(code, str) and code and code != self.cfg.get("acestep_ui_language"):
            self.cfg["acestep_ui_language"] = code
            save_config(self.cfg)
            log.info("ACE-Step UI language: %s", code)
            if self.cfg.get("language") == "acestep":
                self.set_language("acestep")

    def set_language(self, pref):
        self.cfg["language"] = pref
        save_config(self.cfg)
        i18n.set_language(pref, self.cfg.get("acestep_ui_language"))
        log.info("Language: %s (%s)", pref, i18n.current())
        self.retext()
        self.update_progress()
        if "external" in self.banners:  # the only banner that stays for the whole session: redraw it translated
            self.show_banner({"key": "external", "kind": "note", "closable": True, "text": t("external_note")})
        if self.page == "loading":
            self.js(f"setLabels({json.dumps(t('retry'))},{json.dumps(t('open_log'))},{json.dumps(t('choose_acestep'))})")

    # ---------- generation progress ----------

    def on_progress_line(self, line):
        """Map ACE-Step's log milestones to a progress value (called from the server output thread)."""
        with self.gen_lock:
            g = self.gen
            new = None
            for rx, pct, phase in PROGRESS_STEPS:
                if rx.search(line):
                    new = (pct, phase)
                    break
            m = PROGRESS_DECODE.search(line)
            if m and g["active"]:
                new = (80 + int(m.group(1)) * 12 // 100, "gen_decode")
            if new:
                starting = new[1] == "gen_plan" or not g["active"]
                if starting:
                    g.update(active=True, pct=0, t0=time.monotonic(), done_at=0.0)
                if new[0] >= g["pct"]:
                    g.update(pct=new[0], phase=new[1])
                if starting:
                    threading.Thread(target=self._progress_ticker, daemon=True).start()
            elif PROGRESS_DONE.search(line) and g["active"]:
                g.update(pct=100, phase="gen_done", done_at=time.monotonic())
            else:
                return
        self.update_progress()

    def _progress_ticker(self):
        """Refresh the elapsed time every second; hide the bar a few seconds after the song is saved."""
        while not self.closing:
            time.sleep(1)
            with self.gen_lock:
                g = self.gen
                if not g["active"]:
                    return
                if g["done_at"] and time.monotonic() - g["done_at"] > 4:
                    g["active"] = False
            self.update_progress()

    def update_progress(self):
        """Show/refresh the progress card floating in the middle of the ACE-Step page."""
        if self.page != "app":
            return
        g = dict(self.gen)
        el = int(time.monotonic() - g["t0"]) if g["t0"] else 0
        state = {"active": g["active"], "pct": max(0, min(100, g["pct"])),
                 "text": t("gen_title", phase=t(g["phase"]) if g["phase"] else "", t=f"{el // 60}:{el % 60:02d}")}
        self.js(f"window.aceApp&&window.aceApp.progress({json.dumps(state)})")

    def reset_progress(self):
        with self.gen_lock:
            self.gen.update(active=False, pct=0, phase="", done_at=0.0)
        self.update_progress()

    # ---------- server info (menu label + server_info.json for the MCP server) ----------

    def parse_server_line(self, line):
        for key, rx, conv in INFO_PATTERNS:
            m = rx.search(line)
            if m:
                self.set_server_info(**{key: conv(m.group(1))})

    def set_server_info(self, **kw):
        changed = {k: v for k, v in kw.items() if self.server_info.get(k) != v}
        if not changed:
            return
        self.server_info.update(changed)
        self.update_info_label()
        self.write_server_info()

    def write_server_info(self, running=True):
        data = dict(self.server_info, app_running=running, app_version=VERSION, url=self.url.rstrip("/"), mode=self.mode,
                    acestep_path=self.repo, acestep_outputs=os.path.join(self.repo, "gradio_outputs"), updated=datetime.now().isoformat(timespec="seconds"))
        try:
            with open(INFO_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            log.warning("Cannot write %s: %s", INFO_PATH, e)

    def poll_models(self):
        """Current DiT model from ACE-Step's API (also reflects a re-initialization from the page)."""
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(self.url + "v1/models", timeout=3) as r:
                data = json.load(r).get("data") or {}
            self.set_server_info(api_enabled=True, dit_model=data.get("default_model") or self.server_info.get("dit_model"))
        except Exception:
            self.set_server_info(api_enabled=False)

    # ---------- start ----------

    def boot(self):
        if not self.busy.acquire(blocking=False):
            return
        try:
            self._boot()
        except Exception as e:
            log.exception("Startup error")
            self.show_error(t("unexpected_title"), str(e))
        finally:
            self.busy.release()
        if self.mode == "managed" and self.page == "app" and not self.update_checked:
            self.update_checked = True
            threading.Thread(target=self.check_updates, daemon=True).start()
        if not self.monitor_started:
            self.monitor_started = True
            threading.Thread(target=self.monitor, daemon=True).start()

    def _boot(self):
        self.window.events.shown.wait(20)
        self.loaded.wait(15)
        self.setup_native()
        self.mode = None
        self.server_info = {}
        self.update_info_label()
        self.set_menu_enabled({"menu_updates", "menu_restart"}, False)
        self.show_loading(t("starting_title"), t("checking_config"))
        if self.cfg_error:
            return self.show_error(t("cfg_invalid_title"), t("cfg_invalid", err=self.cfg_error, path=CONFIG_PATH))
        if not self.is_acestep_folder(self.repo):
            return self.show_error(t("notfound_title"), t("notfound", path=self.repo, config=CONFIG_PATH), choose=True)
        pid = winsys.listener_pid(self.port)
        if pid is None:
            self.mode = "managed"
            self.set_menu_enabled({"menu_updates", "menu_restart"}, True)
            self.start_server_and_wait(t("starting_title"))
        elif pid > 0 and winsys.is_acestep_process(pid, self.repo):
            self.mode = "external"
            log.info("External server detected (PID %s): external server mode", pid)
            self.show_banner({"key": "external", "kind": "note", "closable": True, "text": t("external_note")})
            self.show_loading(t("connecting_title"), t("connecting_status"))
            self.wait_ready()
        else:
            name = winsys.process_name(pid) if pid > 0 else t("unknown")
            self.show_error(t("port_busy_title"), t("port_busy", port=self.port, name=name, pid=pid, config=CONFIG_PATH))

    @staticmethod
    def is_acestep_folder(path):
        return os.path.isfile(os.path.join(path, "pyproject.toml")) and os.path.isdir(os.path.join(path, "acestep"))

    def choose_acestep(self):
        res = self.window.create_file_dialog(webview.FileDialog.FOLDER, directory=os.path.expanduser("~"))
        if not res:
            return
        path = os.path.abspath(res[0] if isinstance(res, (list, tuple)) else res)
        if not self.is_acestep_folder(path):
            return self.show_error(t("notfound_title"), t("notfound_bad_choice", path=path), choose=True)
        self.cfg["acestep_path"] = path
        save_config(self.cfg)
        self.repo = path
        log.info("ACE-Step folder set to %s", path)
        self.boot()

    def start_server_and_wait(self, title):
        self.show_loading(title, t("starting_server"))
        self.console.clear()
        self.console_partial = ""
        try:
            ffmpeg = self.server.start()
        except Exception as e:
            self.show_error(t("cannot_start_title"), str(e))
            return False
        if ffmpeg:
            self.hide_banner("ffmpeg")
        else:
            self.info(t("ffmpeg_text"), title=t("ffmpeg_title"), kind="warn", key="ffmpeg")
        self.start_head = self.git_head()
        self.dismissed_head = None
        log.info("Server started, ACE-Step HEAD: %s", self.start_head)
        return self.wait_ready()

    def http_ok(self):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(self.url, timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def wait_ready(self):
        t0 = time.monotonic()
        while not self.closing:
            if self.http_ok():
                log.info("ACE-Step answers on %s after %.0f s", self.url, time.monotonic() - t0)
                self.show_app()
                self.poll_models()
                return True
            if self.mode == "managed":
                if not self.server.alive():
                    code = self.server.proc.poll() if self.server.proc else "?"
                    self.server.stop()
                    self.show_error(t("crashed_start_title"), t("crashed_start", code=code, log=SERVER_LOG))
                    return False
                if time.monotonic() - self.server.last_output > STALL_SECONDS:
                    self.server.stop()
                    self.show_error(t("stall_title"), t("stall", min=STALL_SECONDS // 60, url=self.url, log=SERVER_LOG))
                    return False
            elif winsys.listener_pid(self.port) is None:
                self.show_error(t("external_closed_title"), t("external_closed"))
                return False
            el = int(time.monotonic() - t0)
            if self.page == "loading":
                status = t("waiting", t=f"{el // 60}:{el % 60:02d}") + (t("first_run_hint") if el > 30 else "")
                self.js(f"document.getElementById('s').textContent={json.dumps(status)}")
                self.push_console()
            time.sleep(0.7)
        return False

    # ---------- git / uv ----------

    def git(self, *args, timeout=15, show=False):
        if not self.git_exe:
            return 1, "git not found"
        if show:
            self.console.append("$ git " + " ".join(args))
        return winsys.run([self.git_exe, *args], self.repo, self.env, timeout,
                          self.console_feed if show else None)

    def git_head(self):
        code, out = self.git("rev-parse", "HEAD")
        return out if code == 0 else None

    def uv_sync(self):
        self.console.append("$ uv sync")
        if not self.uv_exe:
            return 1, "uv not found"
        return winsys.run([self.uv_exe, "sync"], self.repo, self.env, 3600, self.console_feed)

    def run_with_console(self, fn, *args, **kw):
        """Run fn while showing its output on the loading screen."""
        result = {}
        th = threading.Thread(target=lambda: result.update(r=fn(*args, **kw)), daemon=True)
        th.start()
        while th.is_alive():
            self.push_console()
            th.join(0.5)
        self.push_console()
        return result["r"]

    # ---------- online updates (A) ----------

    def check_updates(self, manual=False):
        if self.mode != "managed":
            if manual:
                self.info(t("updates_disabled"))
            return
        if self.busy.locked():
            if manual:
                self.info(t("busy"))
            return
        code, out = self.git("fetch", "--quiet", timeout=10)
        if code != 0:
            log.info("git fetch failed (no network?): %s", out if code else "timeout")
            if manual:
                self.info(t("fetch_failed"))
            return
        code, upstream = self.git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if code != 0:
            if manual:
                self.info(t("no_upstream"))
            return
        _, count = self.git("rev-list", "--count", "HEAD..@{u}")
        n = int(count) if count.isdigit() else 0
        if n == 0:
            log.info("No updates (%s)", upstream)
            if manual:
                self.info(t("up_to_date", upstream=upstream))
            return
        _, up_hash = self.git("rev-parse", "@{u}")
        if not manual and up_hash == self.cfg.get("skip_version"):
            log.info("Update %s skipped by the user", up_hash)
            return
        _, titles = self.git("log", "--format=%h %s", "-n", "5", "HEAD..@{u}")
        self.pending_update = up_hash
        log.info("Update available: %s commits, %s", n, up_hash)
        self.show_banner({
            "key": "update", "kind": "update",
            "title": t("update_title_1", upstream=upstream) if n == 1 else t("update_title_n", n=n, upstream=upstream),
            "text": t("last_commits") if n <= 5 else t("last_5_commits"),
            "items": titles.splitlines(),
            "buttons": [[t("btn_update_now"), "now", True], [t("btn_later"), "later"], [t("btn_skip"), "skip"]],
        })

    def check_launch_command(self):
        warnings = []
        try:
            with open(os.path.join(self.repo, "pyproject.toml"), encoding="utf-8") as f:
                if not re.search(r'(?m)^\s*acestep\s*=\s*"', f.read()):
                    warnings.append(t("warn_no_script"))
        except OSError:
            warnings.append(t("warn_pyproject"))
        try:
            with open(os.path.join(self.repo, "acestep", "acestep_v15_pipeline.py"), encoding="utf-8") as f:
                src = f.read()
            m = re.search(r'"--port".{0,120}?default=(\d+)', src, re.S)
            if '"--port"' not in src:
                warnings.append(t("warn_no_port"))
            elif m and int(m.group(1)) != 7860:
                warnings.append(t("warn_port_default", new=m.group(1), port=self.port))
            if self.cfg.get("enable_api") and '"--enable-api"' not in src:
                warnings.append(t("warn_no_enable_api"))
        except OSError:
            warnings.append(t("warn_no_pipeline"))
        return warnings

    def do_update(self):
        if not self.busy.acquire(blocking=False):
            return self.info(t("busy"))
        try:
            self.hide_banner("update")
            code, st = self.git("status", "--porcelain")
            dirty = [l for l in st.splitlines() if l[3:].strip().strip('"') != ".env"]
            if code != 0 or dirty:
                files = "\n".join(dirty[:10]) or st
                return self.info(t("dirty", files=files), title=t("dirty_title"), kind="warn", key="dirty")
            old = self.git_head()
            self._updlog(f"Before update: HEAD={old}")
            self.show_loading(t("updating_title"), t("step1"))
            self.console.clear()
            self.server.stop()
            self.show_loading(t("updating_title"), t("step2"))
            code, out = self.run_with_console(self.git, "pull", "--ff-only", timeout=300, show=True)
            failed = None if code == 0 else "git pull --ff-only"
            if not failed:
                self.show_loading(t("updating_title"), t("step3"))
                code, out = self.run_with_console(self.uv_sync)
                failed = None if code == 0 else "uv sync"
            if failed:
                detail = out.splitlines()[-1] if out else ("timeout" if code is None else f"code {code}")
                self._updlog(f"Step failed: {failed} ({detail}). Restoring {old}")
                self.show_loading(t("restoring_title"), f"git reset --hard {old[:8]}")
                c1, _ = self.run_with_console(self.git, "reset", "--hard", old, show=True)
                c2, _ = self.run_with_console(self.uv_sync)
                self._updlog(f"Restore: git reset {'ok' if c1 == 0 else 'FAILED'}, uv sync {'ok' if c2 == 0 else 'FAILED'}")
                ok = self.start_server_and_wait(t("restart_prev_title"))
                msg = t("update_failed", step=failed, detail=detail, old=old[:8], log=UPDATES_LOG)
                if c1 != 0 or c2 != 0:
                    msg += t("restore_problems")
                if ok:
                    self.info(msg, title=t("update_failed_title"), kind="warn", key="update-failed")
                else:
                    self.show_error(t("update_failed_title"), msg)
                return
            new = self.git_head()
            self._updlog(f"Updated: {old} -> {new}")
            warnings = self.check_launch_command()
            self.show_loading(t("updating_title"), t("step4"))
            if self.start_server_and_wait(t("restart_updated_title")):
                if warnings:
                    self._updlog("Launch command warnings: " + "; ".join(warnings))
                    self.info(t("launch_check", items="\n- ".join(warnings)), title=t("launch_check_title"),
                              kind="warn", key="launch")
                else:
                    self.info(t("updated_ok", hash=new[:8]), key="updated")
            elif warnings:
                self.js(f"showError({json.dumps(t('start_failed_after_update'))},"
                        f"{json.dumps(t('possible_cause', items='; '.join(warnings)))},false)")
        except Exception as e:
            log.exception("Error during the update")
            self.show_error(t("update_error_title"), str(e))
        finally:
            self.busy.release()

    def _updlog(self, text):
        log.info(text)
        with open(UPDATES_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")

    # ---------- update made outside the app (B), monitoring, songs folder ----------

    def monitor(self):
        last_head = last_models = time.monotonic()
        while not self.closing:
            time.sleep(5)
            if self.page == "app" and time.monotonic() - last_models >= MODELS_POLL_SECONDS:
                last_models = time.monotonic()
                self.poll_models()
                self.poll_acestep_language()
            if self.mode == "external" and self.page == "app" and winsys.listener_pid(self.port) is None:
                self.show_error(t("external_closed_title"), t("external_closed"))
                continue
            if self.mode != "managed" or self.page != "app" or self.busy.locked():
                continue
            if self.server.proc and not self.server.alive():
                code = self.server.proc.poll()
                if self.busy.acquire(blocking=False):
                    try:
                        self.server.stop()
                        self.show_error(t("crashed_title"), t("crashed", code=code, log=SERVER_LOG))
                    finally:
                        self.busy.release()
                continue
            if time.monotonic() - last_head >= HEAD_CHECK_SECONDS:
                last_head = time.monotonic()
                self.check_head()

    def check_head(self):
        if self.mode != "managed" or self.page != "app" or self.busy.locked() or not self.start_head:
            return
        if not self.head_lock.acquire(blocking=False):
            return
        try:
            head = self.git_head()
            if not head or head == self.start_head:
                return
            code, gitdir = self.git("rev-parse", "--absolute-git-dir")
            anomalies = [n for n in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD")
                         if code == 0 and os.path.exists(os.path.join(gitdir, n))]
            if self.git("symbolic-ref", "-q", "HEAD")[0] != 0:
                anomalies.append("detached HEAD")
            if anomalies:
                if self.anomaly_logged != head:
                    self.anomaly_logged = head
                    log.info("ACE-Step HEAD changed to %s but the repository is in an unusual state (%s): "
                             "no dialog shown", head, ", ".join(anomalies))
                return
            self.changed_head = head
            if head == self.dismissed_head or "head" in self.banners:
                return
            log.info("ACE-Step HEAD changed outside the app: %s -> %s", self.start_head, head)
            self.show_banner({
                "key": "head", "kind": "modal", "text": t("head_changed"),
                "buttons": [[t("btn_restart"), "restart", True], [t("btn_continue"), "continue"]],
            })
        finally:
            self.head_lock.release()

    def restart_after_external_update(self):
        if not self.busy.acquire(blocking=False):
            return
        try:
            self.show_loading(t("restart_updated_title"), t("stopping"))
            self.console.clear()
            self.server.stop()
            self.show_loading(t("restart_updated_title"), t("syncing"))
            code, _ = self.run_with_console(self.uv_sync)
            if code != 0:
                log.warning("uv sync failed (%s): starting anyway", code)
            if self.start_server_and_wait(t("restart_updated_title")) and code != 0:
                self.info(t("sync_failed", log=SERVER_LOG), kind="warn", key="sync")
        finally:
            self.busy.release()

    # ---------- actions ----------

    def banner_action(self, key, value):
        self.banners.pop(key, None)
        if key == "update":
            if value == "now":
                self.do_update()
            elif value == "skip" and self.pending_update:
                self.cfg["skip_version"] = self.pending_update
                save_config(self.cfg)
                log.info("Version skipped: %s", self.pending_update)
        elif key == "head":
            if value == "restart":
                self.restart_after_external_update()
            else:
                self.dismissed_head = self.changed_head
                log.info("Restart postponed by the user (HEAD %s)", self.changed_head)

    def menu_check_updates(self):
        if self.mode != "managed":
            return self.info(t("updates_disabled"))
        self.check_updates(manual=True)

    def menu_restart(self):
        if self.mode != "managed":
            return self.info(t("restart_disabled"))
        if self.busy.locked():
            return self.info(t("busy"))
        if not self.confirm_lock.acquire(blocking=False):  # only one confirmation at a time
            return
        try:
            ok = self.window.create_confirmation_dialog(t("restart_confirm_title"), t("restart_confirm"))
        finally:
            self.confirm_lock.release()
        if not ok or not self.busy.acquire(blocking=False):
            return
        try:
            self.show_loading(t("restarting_title"), t("stopping"))
            self.server.stop()
            self.start_server_and_wait(t("restarting_title"))
        finally:
            self.busy.release()

    def open_outputs(self):
        path = os.path.join(self.repo, "gradio_outputs")
        if os.path.isdir(path):
            os.startfile(path)
        else:
            self.info(t("outputs_missing", path=path))

    def open_log(self):
        os.startfile(SERVER_LOG if os.path.exists(SERVER_LOG) else LOG_DIR)

    def shutdown(self):
        self.closing = True
        if self.mode == "managed":
            self.server.stop()
        self.write_server_info(running=False)
        log.info("App closed")


APP = None


def main():
    global APP
    setup_logging()
    if not winsys.acquire_single_instance():
        winsys.focus_existing_window(APP_TITLE)
        return
    cfg, cfg_error = load_config()
    i18n.set_language(cfg.get("language"), cfg.get("acestep_ui_language"))
    APP = App(cfg, cfg_error)
    log.info("App start %s (frozen=%s, language=%s) config=%s", VERSION, FROZEN, i18n.current(), CONFIG_PATH)

    webview.settings["ALLOW_DOWNLOADS"] = True
    if os.environ.get("ACESTEP_APP_DEBUG_PORT"):  # automated tests only
        webview.settings["REMOTE_DEBUGGING_PORT"] = int(os.environ["ACESTEP_APP_DEBUG_PORT"])

    # Titles are replaced by the native names/texts in App.setup_native (needed for the language switch)
    menu = [
        MenuAction(t("menu_updates"), APP.menu_check_updates),
        MenuAction(t("menu_open_songs"), APP.open_outputs),
        MenuAction(t("menu_log"), APP.open_log),
        MenuAction(t("menu_restart"), APP.menu_restart),
        Menu(t("menu_language"), [
            MenuAction(t("lang_auto"), lambda: APP.set_language("auto")),
            MenuSeparator(),
            MenuAction(t("lang_en"), lambda: APP.set_language("en")),
            MenuAction(t("lang_it"), lambda: APP.set_language("it")),
            MenuSeparator(),
            MenuAction(t("lang_acestep"), lambda: APP.set_language("acestep")),
        ]),
    ]
    APP.window = webview.create_window(
        APP_TITLE, html=LOADING_HTML.replace("{ICON}", APP.icon_uri), js_api=Api(),
        width=cfg["window_width"], height=cfg["window_height"], min_size=(960, 600),
        resizable=True, menu=menu,
    )
    APP.window.events.loaded += APP.on_loaded
    if os.environ.get("ACESTEP_APP_DEBUG_PORT"):  # automated tests drive menu actions without the mouse
        APP.window.expose(APP.set_language, APP.menu_check_updates)
    webview.start(APP.boot, private_mode=False, storage_path=os.path.join(APP_DIR, "webview_data"),
                  icon=ICON_ICO)
    APP.shutdown()
    logging.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
