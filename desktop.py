import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import httpx
import uvicorn

APP_URL = "http://127.0.0.1:8000"

LOADING_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body { margin: 0; height: 100%; background: #0b0b0e; overflow: hidden; }
  body {
    font-family: ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace;
    color: #d6d6d6; display: flex; align-items: center; justify-content: center;
    font-size: 14px; line-height: 1.7;
  }
  .logo-row { display: flex; align-items: center; gap: 12px; }
  .brand { font-weight: 700; letter-spacing: 0.5px; }
  .ver { color: #6b6b72; font-size: 11px; margin-left: 2px; }
  #status { margin-top: 14px; color: #8b8b92; font-size: 12.5px; }
  #status::before { content: '> '; color: __ACCENT__; }
  .cursor { display: inline-block; width: 8px; height: 14px; background: __ACCENT__;
            vertical-align: text-bottom; animation: blink 1.1s steps(2, start) infinite; }
  @keyframes blink { to { visibility: hidden; } }
</style>
</head>
<body>
  <div>
    <div class="logo-row">
      <svg width="34" height="34" viewBox="0 0 128 128"><rect x="3" y="3" width="122" height="122" rx="20" fill="#0b0b0e" stroke="#26262c" stroke-width="5"/><rect x="32" y="32" width="64" height="64" fill="__ACCENT__"/><text x="64" y="67" text-anchor="middle" dominant-baseline="middle" font-family="monospace" font-weight="800" font-size="36" fill="#ffffff">1s</text></svg>
      <span class="brand">Su1ra</span><span class="ver">v0.2.0</span>
    </div>
    <div id="status">starting api server<span class="cursor"></span></div>
  </div>
  <script>
    function setStatus(text) {
      var el = document.getElementById('status');
      if (el) el.innerHTML = text + '<span class="cursor"></span>';
    }
  </script>
</body>
</html>"""

ERROR_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><style>
  html, body { margin: 0; height: 100%; background: #0b0b0e; }
  body { font-family: ui-monospace, Menlo, Consolas, monospace; color: #d6d6d6;
         display: flex; align-items: center; justify-content: center; font-size: 13.5px; }
  code { color: #e04a6e; }
</style></head>
<body>
  <div>
    <div style="color:#e04a6e">&gt; could not start the ollama server</div>
    <p style="color:#8b8b92">check that ollama is installed, or start it manually in a terminal:</p>
    <p><code>ollama serve</code></p>
  </div>
</body>
</html>"""


def ollama_url():
    import store

    return (store.get_setting("ollama_url") or "http://localhost:11434").rstrip("/")


def backend_ready():
    try:
        httpx.get(f"{APP_URL}/api/settings", timeout=0.5)
        return True
    except Exception:
        return False


def start_server():
    from main import app

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


def ollama_ready(url):
    try:
        httpx.get(f"{url}/api/version", timeout=0.8)
        return True
    except Exception:
        return False


def find_ollama_binary():
    found = shutil.which("ollama")
    if found:
        return found
    for candidate in ("/usr/local/bin/ollama", "/usr/bin/ollama"):
        if Path(candidate).exists():
            return candidate
    return None


def set_status(window, text):
    try:
        window.evaluate_js(f"setStatus({text!r})")
    except Exception:
        pass


def wait_for_backend(window):
    for _ in range(100):
        if backend_ready():
            print("[su1ra] backend ready", flush=True)
            return True
        time.sleep(0.1)
    print("[su1ra] backend never became ready", flush=True)
    return False


def ensure_ollama(window):
    url = ollama_url()
    if ollama_ready(url):
        print("[su1ra] ollama detected", flush=True)
        set_status(window, "ollama server detected")
        return True
    print("[su1ra] starting ollama…", flush=True)
    set_status(window, "starting ollama server…")
    try:
        resp = httpx.post(f"{APP_URL}/api/connect", timeout=70.0)
        data = resp.json()
    except Exception as exc:
        print(f"[su1ra] /api/connect failed: {exc}", flush=True)
        data = {"ok": False}
    if data.get("ok"):
        print("[su1ra] ollama is up", flush=True)
        set_status(window, "ollama is up")
        return True
    print(f"[su1ra] ollama failed: {data.get('error')}", flush=True)
    return False


if not backend_ready():
    threading.Thread(target=start_server, daemon=True).start()

import webview

import store as su1ra_store

su1ra_store.init_db()
accent = su1ra_store.get_setting("accent") or "#bf264a"

window = webview.create_window(
    "Su1ra",
    html=LOADING_HTML.replace("__ACCENT__", accent),
    width=1280,
    height=820,
    min_size=(760, 560),
    background_color="#0b0b0e",
)


def boot():
    ok = wait_for_backend(window) and ensure_ollama(window)
    if ok:
        print("[su1ra] window -> app", flush=True)
        window.load_url(APP_URL + "/")
    else:
        print("[su1ra] window -> error screen", flush=True)
        window.load_html(ERROR_HTML)


threading.Thread(target=boot, daemon=True).start()
webview.start(debug=os.environ.get("SU1RA_DEBUG") == "1")
