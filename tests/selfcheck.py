"""Autocontrollo senza interfaccia: uv run python tests/selfcheck.py"""

import io
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402
import winsys  # noqa: E402

REPO = app.DEFAULTS["acestep_path"]

# 1. PATH ricostruito dal registro anche se il processo parte con un PATH minimo (doppio clic da Esplora file)
saved = os.environ["PATH"]
os.environ["PATH"] = r"C:\Windows\System32"
try:
    env = winsys.build_env()
    assert winsys.which("ffmpeg", env), "ffmpeg non trovato col PATH del registro"
    assert winsys.which("uv", env) and winsys.which("git", env)
    assert env["PYTHONIOENCODING"] == "utf-8" and "VIRTUAL_ENV" not in env
finally:
    os.environ["PATH"] = saved
print("ok PATH dal registro")

# 2. controllo del comando di avvio dopo un aggiornamento
a = app.App(dict(app.DEFAULTS), None)
assert a.check_launch_command() == [], a.check_launch_command()
with tempfile.TemporaryDirectory() as tmp:
    os.makedirs(os.path.join(tmp, "acestep"))
    with open(os.path.join(tmp, "pyproject.toml"), "w") as f:
        f.write('[project.scripts]\nacestep-ui = "x:main"\n')
    with open(os.path.join(tmp, "acestep", "acestep_v15_pipeline.py"), "w") as f:
        f.write('parser.add_argument("--listen", default=8000)\n')
    a.repo = tmp
    w = a.check_launch_command()
    assert len(w) == 3, w  # no acestep script, no --port, no --enable-api
print("ok controllo comando di avvio")

# 3. riconoscimento del processo ACE-Step (cartella di lavoro dentro il repository)
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"], cwd=REPO)
try:
    assert winsys.is_acestep_process(p.pid, REPO)
    assert not winsys.is_acestep_process(os.getpid(), REPO)
    assert not winsys.is_acestep_process(p.pid, REPO + "-altro")
finally:
    p.kill()
print("ok riconoscimento processo")

# 4. timeout: il job uccide il comando
code, _ = winsys.run([sys.executable, "-c", "import time; time.sleep(30)"], None, None, 1)
assert code is None
print("ok timeout con job")

# 5. output con \r (barre tqdm) diviso in righe, spazi iniziali conservati
got = []
winsys.read_lines(io.BytesIO(b" M a\nprog 1%\rprog 2%\rfine\n"), lambda l, part: None if part else got.append(l))
assert got == [" M a", "prog 1%", "prog 2%", "fine"], got
code, out = winsys.run([shutil.which("cmd"), "/c", "echo  X"], None, None, 10)
assert out.startswith(" X") or out == "X", repr(out)
print("ok lettura output")
# 6. one version everywhere
import re  # noqa: E402
from version import VERSION  # noqa: E402

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pyproj = re.search(r'(?m)^version\s*=\s*"(.+)"', open(os.path.join(root, "pyproject.toml"), encoding="utf-8").read())[1]
mcpv = re.search(r'(?m)^VERSION\s*=\s*"(.+)"', open(os.path.join(root, "mcp", "music_studio_mcp.py"), encoding="utf-8").read())[1]
assert VERSION == pyproj == mcpv, (VERSION, pyproj, mcpv)
print("ok versione", VERSION)
print("TUTTO OK")
