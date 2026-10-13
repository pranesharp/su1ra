"""Standalone probe: can we open a SECOND pywebview window at DDG's challenge
and read its cookies back? Run this BEFORE wiring the captcha flow into the app.

    .venv/bin/python report/report/captcha-probe.py

The window loads duckduckgo.com as its TOP-LEVEL page (not an iframe — DDG
sends X-Frame-Options: SAMEORIGIN, so framing is impossible). Solve any captcha
if one appears, then close the window. The script prints every cookie it can
see for duckduckgo.com and exits.

What we're testing:
  1. A SECOND window opens fine under Hyprland/Wayland (not just the main one).
  2. window.get_cookies() returns real Set-Cookie strings on GTK/WebKit.
  3. The DDG clearance cookie (if any) is visible from Python.

If (1) or (2) fails here, the in-app captcha flow is not worth building.
"""

import sys
import threading
import time

import webview

COOKIES = []
URL = "https://duckduckgo.com/"


def read_cookies(window):
    """Read the window's cookie jar, print it, and close the window."""
    global COOKIES
    try:
        COOKIES = window.get_cookies() or []
    except Exception as exc:  # pragma: no cover
        print(f"[probe] get_cookies failed: {exc}", flush=True)
        COOKIES = []
    print(f"[probe] read {len(COOKIES)} cookie(s)", flush=True)
    for c in COOKIES:
        print(f"[probe]   {c}", flush=True)
    try:
        window.destroy()
    except Exception:
        pass


def main():
    window = webview.create_window(
        "Su1ra captcha probe", URL, width=900, height=700,
    )

    # Give the user time to solve the captcha, then read cookies on close.
    def waiter():
        # Wait until the window is gone (user closed it) or a timeout.
        for _ in range(600):  # up to 5 min
            time.sleep(0.5)
            try:
                if not window.events.closed.is_set():
                    continue
            except Exception:
                pass
            break
        read_cookies(window)

    window.events.loaded += lambda: threading.Thread(target=waiter, daemon=True).start()
    webview.start()

    print(f"[probe] final cookie count: {len(COOKIES)}", flush=True)
    if not COOKIES:
        print("[probe] RESULT: no cookies readable — captcha flow NOT viable as-is",
              flush=True)
        sys.exit(1)
    print("[probe] RESULT: cookies readable — captcha flow is viable", flush=True)


if __name__ == "__main__":
    main()
