"""README görselleri: assets/demo.gif + plots/*.png (geçici veritabanında demo verisiyle).

Kullanım: python scripts/readme_gorselleri.py   (playwright + chromium gerekir: pip install -e ".[dev]")
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable
PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
home = tempfile.mkdtemp(prefix="rlpanel_demo_")
env = dict(os.environ, RLPANEL_HOME=home, RLPANEL_SERVER=BASE, RLPANEL_NO_BROWSER="1", PYTHONIOENCODING="utf-8")


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=5) as r:
        return json.loads(r.read())


server = subprocess.Popen([PY, "-m", "rlpanel", "serve", "--port", str(PORT), "--no-browser"], env=env)
for _ in range(60):
    try:
        get("/api/health"); break
    except Exception:
        time.sleep(0.5)
demo = subprocess.Popen([PY, "-u", str(REPO / "scripts" / "demo.py")], env=env, stdout=subprocess.PIPE, text=True,
                        encoding="utf-8")
# canlı run oluşana kadar bekle (demo.py önce 3 bitmiş seed yazar)
live_id = None
for _ in range(240):
    line = demo.stdout.readline()
    if "Canlı demo:" in line:
        live_id = int(line.strip().rsplit("/", 1)[1]); break
print("canlı run:", live_id)

out_assets, out_plots = REPO / "assets", REPO / "plots"
out_plots.mkdir(exist_ok=True)
frames = []
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1360, "height": 820}, device_scale_factor=1)
    page.add_init_script("try{localStorage.setItem('rlpanel-theme','light')}catch(e){}")
    page.goto(f"{BASE}/#/run/{live_id}")
    page.wait_for_timeout(1200)
    for i in range(42):
        frames.append(Image.open(io.BytesIO(page.screenshot())).convert("RGB"))
        page.wait_for_timeout(900)
    page.screenshot(path=str(out_plots / "canli_run.png"))
    page.goto(f"{BASE}/#/")
    page.wait_for_timeout(2000)
    page.screenshot(path=str(out_plots / "ana_sayfa.png"))
    ids = ",".join(str(i) for i in range(1, 4))
    page.goto(f"{BASE}/#/compare?ids={ids}")
    page.wait_for_timeout(3000)
    page.screenshot(path=str(out_plots / "karsilastirma.png"))
    b.close()

demo.kill(); server.kill()
small = [f.resize((960, int(960 * f.height / f.width)), Image.LANCZOS) for f in frames]
pal = [f.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in small]
gif = out_assets / "demo.gif"
pal[0].save(gif, save_all=True, append_images=pal[1:], duration=180, loop=0, optimize=True)
print(gif, round(gif.stat().st_size / 2**20, 2), "MB", len(pal), "kare")
