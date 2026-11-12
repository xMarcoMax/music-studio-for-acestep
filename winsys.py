"""Funzioni Windows di basso livello: Job Object, PATH dal registro, istanza singola, porte."""

import ctypes
import os
import shutil
import subprocess
import threading
import time
import winreg
from ctypes import wintypes

import psutil

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")

k32.CreateJobObjectW.restype = wintypes.HANDLE
k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.CreateMutexW.restype = wintypes.HANDLE
k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]

CREATE_SUSPENDED = 0x00000004
CREATE_NO_WINDOW = 0x08000000
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BASIC_LIMIT(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BASIC_LIMIT),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class Job:
    """Job Object con KILL_ON_JOB_CLOSE: se l'app muore (anche bloccata e poi uccisa),
    Windows chiude l'handle e termina tutti i processi del job, figli compresi."""

    def __init__(self):
        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(self.handle, JobObjectExtendedLimitInformation,
                                           ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())

    def spawn(self, cmd, cwd, env):
        """Avvia sospeso, assegna al job e solo dopo riprende: nessun figlio può sfuggire."""
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, creationflags=CREATE_SUSPENDED | CREATE_NO_WINDOW,
        )
        if not k32.AssignProcessToJobObject(self.handle, int(proc._handle)):
            err = ctypes.get_last_error()
            proc.kill()
            raise ctypes.WinError(err)
        ntdll.NtResumeProcess(int(proc._handle))
        return proc

    def terminate(self):
        if self.handle:
            k32.TerminateJobObject(self.handle, 1)

    def close(self):
        if self.handle:
            k32.CloseHandle(self.handle)
            self.handle = None


def read_lines(stream, on_line):
    """Legge l'output in blocchi e lo divide su \\n e \\r (barre di avanzamento tqdm)."""
    buf = ""
    while True:
        chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="replace")
        parts = buf.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        buf = parts.pop()
        for p in parts:
            on_line(p, False)
        if buf:
            on_line(buf, True)  # riga parziale: segnala comunque attività
    if buf:
        on_line(buf, False)


def run(cmd, cwd, env, timeout, on_line=None):
    """Esegue un comando (git, uv) senza console, in un job: al timeout muore tutto l'albero.
    Ritorna (codice, output). Codice None = timeout."""
    job = Job()
    lines = []
    try:
        proc = job.spawn(cmd, cwd, env)

        def collect(line, partial):
            if not partial:
                lines.append(line)
            if on_line:
                on_line(line, partial)

        t = threading.Thread(target=read_lines, args=(proc.stdout, collect), daemon=True)
        t.start()
        try:
            code = proc.wait(timeout)
        except subprocess.TimeoutExpired:
            job.terminate()
            proc.wait(5)
            code = None
        t.join(5)
        # non togliere gli spazi iniziali: «git status --porcelain» li usa nelle colonne
        return code, "\n".join(lines).rstrip().lstrip("\n")
    finally:
        job.terminate()
        job.close()


# ---------- PATH dal registro ----------

def _reg_path(root, key):
    try:
        with winreg.OpenKey(root, key) as k:
            val, typ = winreg.QueryValueEx(k, "Path")
    except OSError:
        return []
    if typ == winreg.REG_EXPAND_SZ:
        val = winreg.ExpandEnvironmentStrings(val)
    return [p for p in val.split(";") if p.strip()]


def build_env():
    """Ambiente per i processi figli. Le app avviate da Esplora file ereditano un PATH
    vecchio: lo ricostruiamo da HKLM e HKCU (come una nuova console)."""
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("_PYI_", "_MEI")) and k.upper() not in (
               "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT")}
    parts = (_reg_path(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")
             + _reg_path(winreg.HKEY_CURRENT_USER, "Environment")
             + os.environ.get("PATH", "").split(";"))
    seen, path = set(), []
    for p in parts:
        key = os.path.normcase(p.strip().rstrip("\\"))
        if key and key not in seen:
            seen.add(key)
            path.append(p.strip())
    env["PATH"] = ";".join(path)
    env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", GRADIO_ANALYTICS_ENABLED="False",
               GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    return env


def which(name, env):
    found = shutil.which(name, path=env["PATH"])
    if not found and name == "uv":
        cand = os.path.expanduser(r"~\.local\bin\uv.exe")
        found = cand if os.path.isfile(cand) else None
    return found


# ---------- porte e processi ----------

def listener_pid(port):
    """PID del processo in ascolto su `port`, None se libera."""
    for c in psutil.net_connections("tcp"):
        if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == port:
            return c.pid or -1
    return None


def is_acestep_process(pid, repo):
    """Vero se il processo in ascolto ha riga di comando, cartella di lavoro
    o eseguibile dentro la cartella di ACE-Step."""
    repo_n = os.path.normcase(os.path.abspath(repo)).rstrip("\\") + "\\"
    try:
        p = psutil.Process(pid)
    except psutil.Error:
        return False
    for getter in (lambda: " ".join(p.cmdline()), p.cwd, p.exe):
        try:
            if repo_n in os.path.normcase(getter()) + "\\":
                return True
        except psutil.Error:
            pass
    return False


def process_name(pid):
    try:
        return psutil.Process(pid).name()
    except psutil.Error:
        return "sconosciuto"


def wait_port_free(port, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if listener_pid(port) is None:
            return True
        time.sleep(0.3)
    return False


# ---------- istanza singola ----------

_mutex = None


def acquire_single_instance(name="Local\\MusicStudioForACEStep-SingleInstance"):
    global _mutex
    _mutex = k32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def focus_existing_window(title, timeout=10):
    """Porta in primo piano la finestra WinForms con il titolo dato (l'altra istanza)."""
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        found = []

        def cb(hwnd, _):
            buf = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, buf, 256)
            cls = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(hwnd, cls, 256)
            if buf.value == title and cls.value.startswith("WindowsForms"):
                found.append(hwnd)
            return True

        u32.EnumWindows(EnumProc(cb), 0)
        if found:
            hwnd = found[0]
            if u32.IsIconic(hwnd):
                u32.ShowWindow(hwnd, 9)  # SW_RESTORE
            u32.SetForegroundWindow(hwnd)
            return True
        time.sleep(0.3)
    return False
