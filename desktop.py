import os
import json
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
      <span class="brand">Su1ra</span><span class="ver">v0.3.1</span>
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

# Links inside the in-app browser pane are `target="_blank"` (that's how Bing
# and most search engines emit results). pywebview's default is to hand those
# to the SYSTEM browser (webbrowser.open -> Firefox), which yanks the user out
# of the app. Turning this off makes `_blank` navigations load in-app instead.
# Honored on GTK, Windows (edgechromium), macOS and Qt.
webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False


# NOTE 2026-10-09: frameless retired after a full bisect (probes v1–v3 in
# %TEMP%/opencode all render fine, yet the real app hangs intermittently:
# zero windows, black screen, 5x Application Hang in the event log).
# No deterministic trigger — flaky race in pywebview WinForms frameless
# init on this machine. Native frame until a different shell/approach.

su1ra_store.init_db()
accent = su1ra_store.get_setting("accent") or "#bf264a"


# --- Native drag & drop (Linux/Wayland) ------------------------------------
# On Wayland/Hyprland a drag reaches the DOM as `text/uri-list` but
# `dataTransfer.getData()` comes back empty, so the webview cannot read the
# dropped file. pywebview's GTK backend DOES capture the real paths (into
# `webview.dom._dnd_state['paths']`) — but it only forwards them to JS by
# attaching `pywebviewFullPath` to entries in `dataTransfer.files`, which is
# empty on Wayland. So we read the captured paths directly and expose them to
# the frontend via a JS API.
#
# This is a no-op on Windows/macOS (the DOM `Files` path already works there).
class NativeDrop:
    """JS bridge: the frontend calls takePaths() on drop to collect any file
    paths pywebview's GTK backend captured from the native drag."""
    def takePaths(self):
        try:
            from webview.dom import _dnd_state

            paths = [p[1] for p in _dnd_state["paths"]]
            _dnd_state["paths"] = []
            return paths
        except Exception:
            return []


class Su1raBridge(NativeDrop):
    """Single js_api object exposed to the frontend (pywebview takes one).

    `capture_pane` is added on Windows where EdgeChromium can snapshot the
    WebView2 surface; on GTK it degrades (returns None) until a GTK capture is
    wired in.
    """

    def capture_pane(self, rect=None):
        """Screenshot the pane (best-effort): result is pushed to the frontend
        via window.__su1raCaptureResult(b64png); '' returns immediately.

        Two prior attempts used WebView2's pythonnet CapturePreview — both froze
        the UI thread (its completion handler needs the very thread the js_api
        bridge runs on). A third tried PowerShell's PrintWindow — it returned a
        BLACK bitmap on this box (not a valid capture of the GPU-composited
        surface). This version touches NOTHING on the UI thread: a worker
        thread takes a full-screen Pillow ImageGrab and crops it to the app
        window's CLIENT area, then to the pane rect if the frontend sent one.

        `rect`: {x, y, w, h} — iframe position/size in viewport CSS px, from the
        frontend. Without it we deliver the full client-area shot.
        """
        try:
            from webview.platforms.winforms import BrowserView
            browser = BrowserView.instances.get(window.uid)
            if browser is None and BrowserView.instances:
                browser = next(iter(BrowserView.instances.values()))
            # BrowserView IS the WinForms form; its client area == the webview.
            hwnd = int(browser.Handle.ToInt64())
        except Exception as exc:
            print(f"[su1ra] capture_pane: window lookup failed: {exc}", flush=True)
            return ""
        if not hwnd:
            return ""

        import base64 as _b64
        import ctypes
        import ctypes.wintypes as _wt
        import io
        import threading

        def _worker():
            try:
                from PIL import ImageGrab
                user32 = ctypes.windll.user32
                shot = ImageGrab.grab()  # full virtual screen, physical px
                # Map the WinForms client area onto the grab. The form runs
                # DPI-virtualized (logical px) while the grab is physical — f
                # re-introduces the real scale (single + multi-monitor safe via
                # the virtual-screen metrics).
                gsm = user32.GetSystemMetrics
                vx, vy, vw, vh = gsm(76), gsm(77), gsm(78), gsm(79)  # SM_X/CXVIRTUALSCREEN...
                if not vw or not vh:
                    vx, vy, vw, vh = 0, 0, gsm(0), gsm(1)  # primary-only fallback
                f = shot.width / vw if vw else 1.0
                rc = _wt.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rc))
                pt = _wt.POINT(0, 0)
                user32.ClientToScreen(hwnd, ctypes.byref(pt))
                cx, cy = int((pt.x - vx) * f), int((pt.y - vy) * f)
                cw, ch = int(rc.right * f), int(rc.bottom * f)
                data = None
                try:
                    # Pane rect: viewport CSS px == client logical px (zoom 100%),
                    # scaled to the grab by f. dpr from the frontend is redundant
                    # with the measured f and is ignored.
                    if isinstance(rect, dict) and float(rect.get("w") or 0) > 24 and float(rect.get("h") or 0) > 24:
                        rx = int(float(rect["x"]) * f)
                        ry = int(float(rect["y"]) * f)
                        x0 = max(cx, min(cx + cw, cx + rx))
                        y0 = max(cy, min(cy + ch, cy + ry))
                        x1 = max(cx, min(cx + cw, cx + rx + int(float(rect["w"]) * f)))
                        y1 = max(cy, min(cy + ch, cy + ry + int(float(rect["h"]) * f)))
                        if x1 - x0 >= 24 and y1 - y0 >= 24:
                            shot = shot.crop((x0, y0, x1, y1))
                        else:
                            shot = shot.crop((cx, cy, cx + cw, cy + ch))
                    else:
                        shot = shot.crop((cx, cy, cx + cw, cy + ch))
                except Exception as exc:
                    print(f"[su1ra] capture_pane: pane crop failed ({exc}); using client area", flush=True)
                    try:
                        shot = shot.crop((cx, cy, cx + cw, cy + ch))
                    except Exception:
                        pass
                buf = io.BytesIO()
                shot.convert("RGB").save(buf, format="PNG")
                data = buf.getvalue()
                if not data or data[:4] != b"\x89PNG":
                    print("[su1ra] capture_pane: grab produced no PNG", flush=True)
                    return
                b64 = _b64.b64encode(data).decode("ascii")
                # Push to the frontend from this WORKER thread — window.evaluate_js
                # marshals to the UI thread itself; we must never block the UI loop.
                window.evaluate_js(
                    "window.__su1raCaptureResult && window.__su1raCaptureResult(%s)"
                    % _js_str(b64)
                )
            except Exception as exc:
                print(f"[su1ra] capture_pane: grab failed: {exc}", flush=True)

        threading.Thread(target=_worker, daemon=True).start()
        return ""  # result arrives asynchronously via __su1raCaptureResult


window = webview.create_window(
    "Su1ra",
    html=LOADING_HTML.replace("__ACCENT__", accent).replace("__APP_URL__", APP_URL),
    width=1280,
    height=820,
    min_size=(760, 560),
    background_color="#0b0b0e",
    frameless=False,
    resizable=True,
    js_api=Su1raBridge(),
)


def _register_native_drop():
    try:
        window.dom.document.events.drop += lambda e: None
        print("[su1ra] native drop hook registered", flush=True)
    except Exception as exc:  # pragma: no cover - platform dependent
        print(f"[su1ra] native drop hook unavailable: {exc}", flush=True)


window.events.loaded += _register_native_drop


def _js_str(s):
    """Safely embed a Python string as a JS string literal."""
    return json.dumps(str(s))


_WIN_PANE_NAV_INSTALLED = False


def _install_new_window_handler_win():
    """Windows (EdgeChromium/WebView2) mirror of the GTK handler.

    pywebview's EdgeChromium backend handles `target="_blank"` in
    `EdgeChrome.on_new_window_request` (edgechromium.py): it marks the request
    handled and calls `load_url(uri)` — which sets `CoreWebView2.Source` on the
    TOP-LEVEL webview, replacing the whole app with the page. We detach that
    handler and route the URL into the browser pane via the same
    `window.__su1raOpenInPane(...)` hook the GTK fix uses.

    Notes on the WinForms backend:
    - `winforms.BrowserView.instances` holds `{uid: BrowserView}` and
      `BrowserView.browser` is the `EdgeChrome` instance;
      `EdgeChrome.webview` is the WinForms `WebView2`.
    - `CoreWebView2` is ONLY safely reachable on the UI thread, and only once
      WebView2 has finished initialising. `events.loaded` fires from the
      JS-bridge thread (non-UI), so we marshal onto the UI thread via
      `wv.Invoke(...)` and poll (briefly) until the controller is ready, then
      detach pywebview's `NewWindowRequested` handler and attach ours.
    """
    global _WIN_PANE_NAV_INSTALLED
    if _WIN_PANE_NAV_INSTALLED:
        return
    try:
        from webview.platforms.winforms import BrowserView
    except Exception as exc:
        print(f"[su1ra] winforms backend unavailable: {exc}", flush=True)
        return

    def _handled(browser, _sender, args):
        # args.get_Uri() → the target="_blank" destination.
        # NewWindowRequested fires on the UI thread, so ExecuteScriptAsync is safe
        # to call directly.
        try:
            args.set_Handled(True)
            uri = str(args.get_Uri())
            if uri:
                wv = getattr(browser, "webview", None)
                if wv is not None:  # Async, best-effort: route into the pane.
                    script = (
                        "window.__su1raOpenInPane && window.__su1raOpenInPane(%s)"
                        % _js_str(uri)
                    )
                    wv.ExecuteScriptAsync(script)
        except Exception as exc:
            print(f"[su1ra] pane nav failed: {exc}", flush=True)

    def _install_locked():
        # MUST run on the UI thread. Detaches pywebview's default (which does
        # load_url → replaces app) and attaches ours.
        browser = BrowserView.instances.get(window.uid)
        if browser is None and BrowserView.instances:
            browser = next(iter(BrowserView.instances.values()))
        edge = getattr(browser, "browser", None)
        wv = getattr(edge, "webview", None)
        if not wv or getattr(wv, "_su1ra_pane_nav", False):
            return False
        try:
            core = wv.CoreWebView2
        except Exception:
            return False  # not ready yet — caller retries
        if core is None:
            return False
        try:  # drop pywebview's default NewWindowRequested (load_url → replaces app)
            core.NewWindowRequested -= edge.on_new_window_request
        except Exception as exc:
            print(f"[su1ra] could not detach edge new-window handler: {exc}", flush=True)
        try:
            # Attach a bound method: pythonnet requires self as first arg.
            core.NewWindowRequested += _handled.__get__(edge, type(edge))
        except Exception as exc:
            print(f"[su1ra] could not attach edge new-window handler: {exc}", flush=True)
            return False
        wv._su1ra_pane_nav = True
        _WIN_PANE_NAV_INSTALLED = True
        print("[su1ra] edge new-window handler installed", flush=True)
        return True

    def _on_ui_thread(action):
        # Marshal `action` (a no-arg callable) onto the WinForms UI thread.
        try:
            wv.Invoke(_Action(action))  # noqa
        except Exception as exc:
            print(f"[su1ra] pane nav: could not marshal to UI thread: {exc}", flush=True)

    try:
        browser = BrowserView.instances.get(window.uid)
        if browser is None and BrowserView.instances:
            browser = next(iter(BrowserView.instances.values()))
        edge = getattr(browser, "browser", None)
        wv = getattr(edge, "webview", None)
        if wv is None:
            print(f"[su1ra] edge new-window handler: no webview (uid={window.uid!r}, instances={len(BrowserView.instances)})", flush=True)
            return
        if getattr(wv, "_su1ra_pane_nav", False):
            return
        # CoreWebView2 is only safely reachable on the UI thread; events.loaded
        # fires from the JS-bridge thread. Marshal the install onto the UI thread
        # and poll (briefly) until the controller is ready.
        from System import Action as _Action

        def _try_lock():
            try:
                return _install_locked()
            except Exception as exc:
                print(f"[su1ra] edge new-window handler: install try failed: {exc}", flush=True)
                return False

        attempts = 0
        while attempts < 40 and not _WIN_PANE_NAV_INSTALLED:
            _on_ui_thread(_try_lock)
            if _WIN_PANE_NAV_INSTALLED:
                break
            time.sleep(0.1)
            attempts += 1
        if not _WIN_PANE_NAV_INSTALLED:
            print("[su1ra] edge new-window handler: CoreWebView2 never became ready", flush=True)
    except Exception as exc:
        print(f"[su1ra] edge new-window handler: setup failed: {exc}", flush=True)


def _install_new_window_handler():
    """Route `target="_blank"` navigations into the browser pane.

    Every Bing/Google result link is `target="_blank"`. There are two platform
    backends to handle:

    - Linux/GTK (WebKitGTK): pywebview's own `decide-policy` handler
      (`on_navigation`) would `load_url` the main webview (replacing the app).
      We detach it and install our own on `decide-policy`, routing the URL to
      the pane's iframe and calling `decision.ignore()`.
    - Windows/EdgeChromium (WebView2): pywebview's `NewWindowRequested` handler
      calls `load_url` too — same end result. We detach and re-route.

    Note (GTK): hooking `create` instead does NOT work — returning a widget from
    that signal crashes WebKit (`std::optional<WindowFeatures>` assertion), and
    returning None lets the default navigation replace the app.
    """
    if os.name == "nt":
        return _install_new_window_handler_win()
    try:
        import gi

        gi.require_version("WebKit2", "4.1")
        from gi.repository import WebKit2

        def on_decide_policy(view, decision, _dtype):
            try:
                if isinstance(decision, WebKit2.NavigationPolicyDecision):
                    action = decision.get_navigation_action()
                    if action.get_frame_name() == "_blank":
                        uri = action.get_request().get_uri()
                        if uri:
                            view.run_javascript(
                                "window.__su1raOpenInPane && window.__su1raOpenInPane(%s)"
                                % _js_str(uri)
                            )
                        # Cancel the navigation so the main webview stays put.
                        decision.ignore()
                        return True
            except Exception as exc:
                print(f"[su1ra] pane nav failed: {exc}", flush=True)
            return False

        # pywebview keeps its GTK BrowserView objects in a class-level registry
        # keyed by window uid (gtk.py: `BrowserView.instances[window.uid] = self`).
        # window.gui is NOT set on the GTK backend, so that path finds nothing.
        from webview.platforms.gtk import BrowserView

        browser = BrowserView.instances.get(window.uid)
        if browser is None and BrowserView.instances:
            # Fall back to any registered view (first window is 'master').
            browser = next(iter(BrowserView.instances.values()))
        wv = getattr(browser, "webview", None)
        if wv is not None:
            if getattr(wv, "_su1ra_pane_nav", False):
                return
            pywebview_nav = getattr(browser, "on_navigation", None)
            try:
                wv.disconnect_by_func(pywebview_nav)
            except Exception as exc:
                print(f"[su1ra] could not detach pywebview nav handler: {exc}", flush=True)
                pywebview_nav = None

            def handler(view, decision, dtype):
                if on_decide_policy(view, decision, dtype):
                    return True
                if pywebview_nav is not None:
                    pywebview_nav(view, decision, dtype)
                return False

            wv.connect("decide-policy", handler)
            wv._su1ra_pane_nav = True
            print("[su1ra] new-window handler installed", flush=True)
            return
        print("[su1ra] new-window handler: no native webview found", flush=True)
    except Exception as exc:  # pragma: no cover - platform dependent
        print(f"[su1ra] new-window handler unavailable: {exc}", flush=True)


window.events.loaded += _install_new_window_handler



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
