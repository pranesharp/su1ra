# Task: in-app browser pane — link clicks open in the WHOLE app (RESOLVED)

Status: **FIXED 2026-10-13 (late), user-verified.** Hypothesis 1 below was right.

## Resolution
pywebview connects its own `decide-policy` handler (`gtk.py:207`
`on_navigation`) at window creation, so it ran first and, with
`OPEN_EXTERNAL_LINKS_IN_BROWSER = False`, called `self.load_url(uri)` on the main
webview before our `ignore()`. Fix in `desktop.py` `_install_new_window_handler`:
`wv.disconnect_by_func(browser.on_navigation)`, connect one wrapper that handles
`_blank` (→ `__su1raOpenInPane` + `ignore()` + `return True`) and delegates
everything else to pywebview's `on_navigation`; `wv._su1ra_pane_nav` guard so it
installs once (`loaded` fires for splash AND app). Follow-ups (Bing redirect
unwrapping for summarize, etc.) are in `session-log.md`.

---
(Original debugging notes below, kept for history.)

## Goal
`/web <query|url>` opens a lightweight browser in the right-hand split pane
(the same pane that hosts the artifact preview / python IDE). Clicking a search
result inside that pane must load the page **in the pane**, with the app intact.

## What works
- `/web laplace` → pane opens, Bing results render in the iframe. ✅
- Typing a URL into the pane's address bar → loads in the pane. ✅
- Badge (`✓ html` / `✗ js` / `✗ blocked`), `[ open externally ]`,
  `[ summarize page ]` all render. ✅

## What is broken
Clicking a result link loads the page **in the whole app** (replaces Su1ra),
instead of in the pane.

## Root cause chain (established with `link-probe.py`)
1. Bing result links are `target="_blank"`.
2. pywebview's GTK backend handles `_blank` in its own `decide-policy` handler
   (`platforms/gtk.py:456 on_navigation`) by calling `webbrowser.open()` →
   **Firefox**. That was the first symptom.
3. Setting `webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False` stopped
   Firefox, but then **nothing** happened.
4. `report/report/link-probe.py` (logs every navigation signal) showed that with
   the iframe sandbox at `allow-scripts allow-same-origin allow-forms`
   (**no `allow-popups`**), clicking produced:
   ```
   DECIDE-POLICY  frame= None  uri= about:blank      <- URL stripped
   (no CREATE at all)
   ```
   With `allow-popups` restored:
   ```
   DECIDE-POLICY  frame= _blank  uri= https://www.bing.com/ck/a?...wikipedia...
   CREATE fired   uri= https://www.bing.com/ck/a?...wikipedia...
   ```
   **So `allow-popups` is what CARRIES the URL** — removing it empties the click.
   (It is NOT what escapes to Firefox; that's `OPEN_EXTERNAL_LINKS_IN_BROWSER`.)

## Attempts made (all failed to fix the "whole app" symptom)
| # | Attempt | Result |
|---|---|---|
| 1 | Remove `allow-popups` from iframe sandbox | Nothing opened at all |
| 2 | `OPEN_EXTERNAL_LINKS_IN_BROWSER = False` | Nothing opened |
| 3 | Hook `create`, return `None` | No change (create never fired) |
| 4 | Hook `create`, `view.load_uri(uri)` | Loaded — but replaced the whole app |
| 5 | Hook `create`, `evaluate_js` + return `None` | Still replaced the app |
| 6 | Hook `create`, return `WebKit2.WebView()` | **CRASH** (`std::optional<WindowFeatures>` assertion) |
| 7 | Hook `decide-policy`, `run_javascript` + `decision.ignore()` | **Still replaces the whole app** ← current state |

## Current code state
- `desktop.py` → `_install_new_window_handler()` hooks **`decide-policy`** on
  `BrowserView.instances[window.uid].webview`, and for `frame_name == '_blank'`
  calls `view.run_javascript("window.__su1raOpenInPane(...)")` then
  `decision.ignore()` and returns `True`.
- `desktop.py` → `webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False`.
- `frontend/src/components/ArtifactPane.jsx` → iframe sandbox is
  `allow-scripts allow-same-origin allow-forms allow-popups`.
- `frontend/src/App.jsx` → `window.__su1raOpenInPane(url)` opens the pane and sets
  `browserUrl` (same path the address bar uses).

## Why attempt 7 probably still fails (hypotheses for next session)
1. **pywebview's own `decide-policy` handler runs too.** Both handlers are
   connected; order matters. pywebview's `on_navigation` may run first and call
   `self.load_url(uri)` (with the setting off) — navigating the main webview
   before ours can `ignore()`. **Try: disconnect pywebview's handler, or connect
   ours with `connect_after`/priority, or set the setting back to `True` and rely
   solely on our `ignore()`.**
2. **`run_javascript` may be async/queued** and not run before the navigation.
3. **The `_blank` navigation may not be the one replacing the app** — the
   replacement might come from the iframe's own top-level navigation escaping.
4. **`decision.ignore()` may not cancel a `_blank`** in this WebKit build.

## Next debugging steps (suggested)
1. Add a print in `on_decide_policy` logging `frame_name`, `uri`, and whether it
   returned `True`. Confirm it fires on the click.
2. Check whether pywebview's `on_navigation` also fires (add a print, or
   monkeypatch `webbrowser.open` to log).
3. Try disconnecting pywebview's handler:
   `wv.disconnect(...)` / or set `OPEN_EXTERNAL_LINKS_IN_BROWSER = True` and let
   our `ignore()` win.
4. Extend `report/report/link-probe.py` to also log `decide-policy` return values
   and whether `ignore()` was called.

## Files
- `desktop.py` — `_install_new_window_handler`, `_js_str`
- `frontend/src/components/ArtifactPane.jsx` — iframe sandbox
- `frontend/src/App.jsx` — `window.__su1raOpenInPane`
- `report/report/link-probe.py` — the diagnostic that found the `allow-popups` cause
