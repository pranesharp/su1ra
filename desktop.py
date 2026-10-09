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
  .pywebview-drag-region { -webkit-app-region: drag; user-select: none; }
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
  <div class="pywebview-drag-region">
    <div class="logo-row">
      <svg width="34" height="34" viewBox="0 0 128 128"><rect x="3" y="3" width="122" height="122" rx="20" fill="#0b0b0e" stroke="#26262c" stroke-width="5"/><rect x="32" y="32" width="64" height="64" fill="__ACCENT__"/><text x="64" y="67" text-anchor="middle" dominant-baseline="middle" font-family="monospace" font-weight="800" font-size="36" fill="#ffffff">1s</text></svg>
      <span class="brand">Su1ra</span><span class="ver">v0.3.0</span>
    </div>
    <div id="status">starting api server<span class="cursor"></span></div>
  </div>
  <script>
    // Self-navigating splash: poll the backend until it answers, then go
    // to the app. Done in-page (not via window.load_url from a Python
    // thread) because cross-thread WebView2 calls intermittently hang the
    // frameless window ("not responding").
    (function () {
      var APP = '__APP_URL__';
      var tries = 0;
      function setStatus(text) {
        var el = document.getElementById('status');
        if (el) el.innerHTML = text + '<span class="cursor"></span>';
      }
      window.setStatus = setStatus;
      var timer = setInterval(function () {
        tries++;
        if (tries === 6) setStatus('warming up local models');
        fetch(APP + '/api/settings', { cache: 'no-store' }).then(function (r) {
          if (!r.ok) throw 0;
          clearInterval(timer);
          setStatus('opening su1ra');
          window.location.replace(APP + '/');
        }).catch(function () {
          // Cold boots (fresh installs, Defender scanning new files) can
          // take a while — give the backend a full minute before the
          // error screen, or users meet it on an otherwise fine start.
          if (tries >= 240) {
            clearInterval(timer);
            document.body.innerHTML = '<div><div style="color:#e04a6e">&gt; could not start the su1ra backend</div>'
              + '<p style="color:#8b8b92">reinstall, or run desktop.py from a terminal to see the error</p></div>';
          }
        });
      }, 250);
    })();
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
    <div style="color:#e04a6e">&gt; could not start the su1ra backend</div>
    <p style="color:#8b8b92">reinstall, or run desktop.py from a terminal to see the error</p>
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
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).resolve().parent / "ollama"
    else:
        bundled = PROJECT_ROOT / "ollama"
    for sub in (".", "bin"):
        for name in ("ollama.exe", "ollama"):
            if (bundled / sub / name).exists():
                return str(bundled / sub / name)
    found = shutil.which("ollama")
    if found:
        return found
    for candidate in ("/usr/local/bin/ollama", "/usr/bin/ollama"):
        if Path(candidate).exists():
            return candidate
    return None


def wait_for_backend():
    for _ in range(100):
        if backend_ready():
            print("[su1ra] backend ready", flush=True)
            return True
        time.sleep(0.1)
    print("[su1ra] backend never became ready", flush=True)
    return False


def ensure_ollama():
    url = ollama_url()
    if ollama_ready(url):
        print("[su1ra] ollama detected", flush=True)
        return True
    print("[su1ra] starting ollama…", flush=True)
    try:
        resp = httpx.post(f"{APP_URL}/api/connect", timeout=70.0)
        data = resp.json()
    except Exception as exc:
        print(f"[su1ra] /api/connect failed: {exc}", flush=True)
        data = {"ok": False}
    if data.get("ok"):
        print("[su1ra] ollama is up", flush=True)
        global ollama_started_by_us
        ollama_started_by_us = bool(data.get("started"))
        return True
    print(f"[su1ra] ollama failed: {data.get('error')}", flush=True)
    return False


if not backend_ready():
    threading.Thread(target=start_server, daemon=True).start()

import webview

import store as su1ra_store


# NOTE 2026-10-09: frameless retired after a full bisect (probes v1–v3 in
# %TEMP%/opencode all render fine, yet the real app hangs intermittently:
# zero windows, black screen, 5x Application Hang in the event log).
# No deterministic trigger — flaky race in pywebview WinForms frameless
# init on this machine. Native frame until a different shell/approach.

su1ra_store.init_db()
accent = su1ra_store.get_setting("accent") or "#bf264a"

window = webview.create_window(
    "Su1ra",
    html=LOADING_HTML.replace("__ACCENT__", accent).replace("__APP_URL__", APP_URL),
    width=1280,
    height=820,
    min_size=(760, 560),
    background_color="#0b0b0e",
    frameless=False,
    resizable=True,
)



def boot():
    # No window calls here by design: the splash page navigates itself once
    # the backend answers (see LOADING_HTML). This thread only warms up the
    # ollama server in parallel. Touching the WebView2 control off the UI
    # thread intermittently hangs the frameless window.
    if not wait_for_backend():
        return
    if ensure_ollama():
        print("[su1ra] ollama ready (splash will navigate)", flush=True)
    else:
        # Ollama missing/down is NOT fatal: the home screen's OllamaSetup
        # callout offers [ start ollama ] / [ install ollama ] in-app.
        print("[su1ra] ollama pending, in-app setup will offer install", flush=True)


ollama_started_by_us = False


def _set_window_icon():
    """Windows taskbar/title icon. pywebview never sets one (WinForms shows
    a generic glyph), so push su1ra.ico onto the native window by title."""
    if os.name != "nt":
        return
    try:
        base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else PROJECT_ROOT
        ico = base / "su1ra.ico"
        if not ico.exists():
            return
        import ctypes

        user32 = ctypes.windll.user32
        hicon = user32.LoadImageW(None, str(ico), 1, 0, 0, 0x10)
        if not hicon:
            return
        for _ in range(300):
            hwnd = user32.FindWindowW(None, "Su1ra")
            if hwnd:
                # PostMessage (async) — never SendMessage across threads here;
                # a synchronous send during WebView2 init can stall the UI.
                user32.PostMessageW(hwnd, 0x80, 0, hicon)
                user32.PostMessageW(hwnd, 0x80, 1, hicon)
                print("[su1ra] window icon set", flush=True)
                return
            time.sleep(0.2)
    except Exception as exc:
        print(f"[su1ra] window icon skipped: {exc}", flush=True)


def _make_frameless_resizable():
    """Keep native edge-resize + Aero snap on a frameless WinForms window.

    pywebview frameless => FormBorderStyle.None, which drops WS_THICKFRAME.
    Re-add THICKFRAME + MIN/MAX boxes so edges snap/resize like a normal
    window, while the titlebar itself stays hidden (our React titlebar
    draws min/max/close). No-op on Linux.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        GWL_STYLE = -16
        WS_THICKFRAME = 0x00040000
        WS_MINIMIZEBOX = 0x00020000
        WS_MAXIMIZEBOX = 0x00010000
        WS_SYSMENU = 0x00080000
        SWP_FRAMECHANGED = 0x0020
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        for _ in range(300):
            hwnd = user32.FindWindowW(None, "Su1ra")
            if hwnd:
                style = user32.GetWindowLongW(hwnd, GWL_STYLE)
                style |= WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
                user32.SetWindowLongW(hwnd, GWL_STYLE, style)
                user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
                print("[su1ra] frameless resize enabled", flush=True)
                return
            time.sleep(0.2)
    except Exception as exc:
        print(f"[su1ra] frameless resize skipped: {exc}", flush=True)


# Icon thread is safe under the native frame (original behavior).
# _make_frameless_resizable stays off — pointless with a native frame.
threading.Thread(target=_set_window_icon, daemon=True).start()
threading.Thread(target=boot, daemon=True).start()
webview.start(debug=os.environ.get("SU1RA_DEBUG") == "1")

# Window closed: stop the ollama server only if this session spawned it.
# A server the user was already running is left untouched.
if ollama_started_by_us:
    print("[su1ra] stopping self-spawned ollama…", flush=True)
    try:
        httpx.post(f"{APP_URL}/api/ollama/stop", timeout=10.0)
    except Exception as exc:
        print(f"[su1ra] ollama stop failed: {exc}", flush=True)
