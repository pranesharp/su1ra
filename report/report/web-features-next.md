# Web-feature handoff — 2026-10-16 (RESOLVED, closed 2026-10-16 later session)

**State: the whole A/B/C batch is implemented.** A (ImageGrab capture) and the B
frontend hardening are built into the fresh dist; B's root cause is proven with a
live reproduction; C re-verified backend-side. What remains is USER
CLICK-THROUGH of the desktop app ([ capture ], `ab: on`, casual summarize) before
committing — per the commit discipline below.

## README for the reader
- Reference mirrors are in the repo root `AGENTS.md` (the `/web browser pane`
  section) and the report copy; this file is the canonical "what's next."
- Long-term bug history lives in `report/report/session-log.md` — append to it,
  don't rewrite.

---

## DONE + VERIFIED (this box, current session)
1. **EdgeChromium link-click fix (covers-app bug)** — `desktop.py._install_new_window_handler_win()`
   (dispatched on `os.name=='nt'`). Finds `winforms.BrowserView.instances` →
   `.browser` (EdgeChrome) → `.webview`, polls for CoreWebView2 on the UI thread
   (up to ~4s), marshals via `wv.Invoke`, detaches pywebview's
   `on_new_window_request` (which called `load_url` → replaced the whole app),
   attaches one that `set_Handled(True)` +
   `ExecuteScriptAsync("window.__su1raOpenInPane(uri)")`. **User-confirmed
   working.** GTK/Linux path untouched.
2. **Adblocker** — backend rewrite proxy `/api/page/view?url=` injects a
   blocklist `<style>` in `<head>`, strips ad scripts/frames/empty divs; pane
   iframe loads it when the `ab: on` toggle is set (`ArtifactPane.jsx` `adblockOn`).
   - **Backend-verified via curl in this session too (200, blocklist injected
     into head). NOT yet user-confirmed in-app — click-through task.**
   - Constraint: uses the backend's httpx egress → hits the same WARP/403 limit
     as summarize for bot-blocked origins (e.g. Wikipedia). On fetchable pages it
     works fully.
3. **A. Screenshot — FIXED (ImageGrab).** `desktop.py.capture_pane` rewritten:
   worker thread does `PIL.ImageGrab.grab()` (full virtual screen) + crops to the
   app window's CLIENT area, then to the pane rect when the frontend sent one.
   Mapping: `GetClientRect` + `ClientToScreen` + virtual-screen metrics + scale
   `f = shot.width / vw` (logical→physical; `dpr` from JS is redundant and
   ignored). Result pushed via `window.evaluate_js("window.__su1raCaptureResult(b64)")`.
   **Mechanics verified against a real window on the live desktop** (grab
   1920x1200, client box `(1,31,785,1167)` inside grab, pane crop 600x400, valid
   PNG). PrintWindow path deleted. **User click-through pending**: [ capture ] in
   the desktop app → screenshot lands in chat → vision model reads it.
4. **B. Casual "thinking" leak — ROOT-CAUSED + frontend-fixed + logged.** Live
   reproduction through the app's own `/api/chat` route:
   - The request DOES reach Ollama with `think:false` (frontend send path is
     correct; suspects 1–2 in the old plan below are REFUTED — the debug log
     proves `body='off'`).
   - **Ollama IGNORES it for the casual loadout model.** `abminicpm52b:latest`
     is a GGUF-only import (`minicpm5-2b-abliterated-IQ4_XS.gguf`, size 1.42 GB)
     whose template is bare `{{ .Prompt }}` — no `{{ if .Think }}` construct, no
     `reasoning` capability. Verified live: identical ' thinking' preamble in
     output with `think:false`, `think` omitted, and a system directive begging
     it not to reason. The preamble arrives in the CONTENT channel (not the
     `thinking` field), so stream_chat's field-detection never collapses it and
     `ChatView.splitThinking` swallowed the whole reply (incl. any real answer)
     into an unclosed think block — chat 65 msg 496 degenerated to 2610 chars of
     pure reasoning and NO answer.
   - Fixes shipped: (i) SU1RA_DEBUG-gated diagnostic log at main.py:1596 printing
     `model / think / body.think / conv.think / code_mode / think-toggle-supported`
     with a warning when think-off is requested on a model that can't honor it
     (shown live in this session); (ii) `splitThinking(content, strictClose)`
     — a FINAL message whose ' thinking' opener has no ' response' closer now
     renders as content (the model really wrote it), so the answer is no longer
     swallowed; streaming keeps the lenient rule to avoid flashing raw text.
   - **No request-level lever exists to actually stop this model thinking** —
     tell the user to switch the casual loadout to a qwen3-family model if
     think-off must suppress reasoning.
5. **C. In-app adblock confirm** — backend re-verified (see 2). Click-through task.

## Old "must-fix" plan (superseded — kept for history)
### A. Screenshot (old state)
- Root cause: `CoreWebView2.CapturePreview` + `time.sleep` + `stream.Read` on the
  js_api bridge thread (== UI thread) deadlocked. Then `PrintWindow` → BLACK
  bitmap (documented broken on this box). Both replaced by ImageGrab (above).

### B. Casual "thinking" leak (old suspects, now resolved)
- Not a send-path bug: `body.think='off'` reaches Ollama (proven by the new
  debug log). The model ignores it (template has no `.Think`; verified with
  `/api/show`). `startModeChat` retag / legacy `default_think` suspects: refuted
  (chat 65 `code_mode=0`, `default_think` unset, loadout_casual_think='off').

## Invariants to preserve (learned the hard way)
- **NEVER block the UI thread.** pywebview js_api methods run on the UI thread;
  any async native completion that also needs the UI thread will deadlock. Do all
  native/network work on a worker thread. The ImageGrab grab+crop lives entirely
  on a worker thread; only the final `evaluate_js` push touches the UI loop
  (pywebview marshals it).
- Link-click: `allow-popups` in the iframe sandbox carries the URL — do not remove.
- Backend httpx egress is Cloudflare-WARP-routed on this box → Wikipedia et al.
  403; the WebView2 iframe (real browser) does not. So the backend probe claims ≠
  what renders/summarizable.

## Model manifests (current, this box)
- Only two models are pulled NOW: `abminicpm52b:latest` (casual loadout; MiniCPM
  5-2b-abliterated GGUF — think toggle NOT honored) and `Qwen3.8-9b:latest`
  (build loadout). The earlier handoff list (qwen3.5:0.8b, gemma4:e4b,
  deepseek-r1:1.5b) was STALE — those models are gone from
  `~/.ollama/models/manifests-v2`. Ollama on the box: 0.40.1 (`/api/show` is POST).

## Commit discipline (updated)
- The broken PrintWindow capture is gone (replaced by ImageGrab — nothing broken
  to hold the commit anymore). Suggested commit covering this batch:
  "web pane: ImageGrab capture (was black-printing PrintWindow), casual-think
  root-cause (MiniCPM GGUF ignores the think toggle) + splitThinking strictClose
  + SU1RA_DEBUG think log, adblock proxy backend-verified; docs"
- History note: the WSL sandbox work is already committed + pushed.
