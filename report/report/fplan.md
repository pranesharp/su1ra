# Su1ra future plans

Living list — newest on top. Checked items move to `session-log.md` when built.
(Shared list: both human and assistant update as things get agreed.)

## Approved / queued
- [x] Auto-context listing injection (always) + mandatory tool-use sentence — built 2026-10-09 (backend only, in installer below)
- [x] README v0.3.0 refresh (workspace section, /mkdir + /cd rows, modes-compared note, Ollama troubleshooting pointer, version strings) — written 2026-10-09, screenshots left for human
- [x] File import Tier 1 (images) + Tier 2 (documents: pdf/docx/pptx/xlsx/csv/text/code) + app-wide drag & drop (incl. Wayland/Hyprland) — built 2026-10-13
- [x] `/web` replaced with an in-app browser pane (split view, URL bar, engine picker, back/fwd/refresh) + page badge (✓ html / ✗ js / ✗ blocked) + `[ summarize page ]` for HTML pages — built 2026-10-13
- [x] Web search `/web` + `/webf` (DDG scrape with custom-API fallback, SSRF-guarded fetch, settings UI) — built 2026-10-13
- [x] Web search captcha flow: DDG bot-challenge detection → in-app `[ solve captcha ]` button → native DDG popup → cookies handed to the backend; distinct "no internet connection" errors — built 2026-10-13
- [x] Web search rework 2026-10-13: **captcha/cookie flow REMOVED** (proved unworkable — DDG's anomaly.js challenge is fingerprint-based, cookies never captured, and each query needed the browser open). Replaced with: multi-target free scrape (DDG → DDG Lite → Mojeek → Startpage) as best-effort fallback; API is the real path; if the API returns 429/quota the app offers a `[ try free scrape ]` button; `/webf` now detects JS-rendered pages and says so instead of summarizing 20 chars
- [x] **`/web` replaced by an in-app browser pane** 2026-10-13 (final shape). All search machinery DELETED — `backend/websearch.py`, `/api/web/search` + `/api/web/fetch`, the search-API settings box, `/webf`, the scrape, the captcha flow. `/web <url or query>` now opens the right-hand split pane as a lightweight browser: URL bar, back/forward/refresh, engine dropdown (Google/Brave/DDG/Yandex/Bing, default Bing), sandboxed iframe, `[ open externally ]`. Google/Brave/DDG block framing (X-Frame-Options) so the pane shows a hint + the external escape hatch; Bing/Yandex frame fine. No API, no key, no scraping.

- [x] Browser pane fixes 2026-10-13 (late): result clicks load in the pane (pywebview nav handler replaced), Bing `ck/a` redirect unwrapping so `[ summarize page ]` works, compact `// summarize page: <title>` chat line, summarize works on a fresh start (no chat yet), pane divider drag no longer sticks + width clamp — details in `session-log.md`

## v2 ideas (discussed, unapproved)
- [ ] Browser pane: track in-iframe navigation (links clicked INSIDE a page) so summarize uses the page actually shown
- [ ] Browser pane: "ask about this page" from chat (pane URL as context), not just the button
- [ ] In-chat allow/disallow approval popup for out-of-bounds ops (pausable agentic loop)
- [ ] `/mkdir` scaffolding contents (bare folder vs starter files)
- [ ] History-stripping of superseded artifacts (context savings on long revision chains)
- [ ] Preview slide/scroll-state preservation across reloads
- [x] **WSL sandbox backend for Windows tool runs** — built + verified 2026-10-16.
      Task doc: `sandbox-wsl-task.md` (all acceptance boxes ticked except the
      Linux regression run, which needs a Linux box). Decision of record stands:
      WSL2 + bubblewrap chosen over Windows-native options (AppContainer reads
      user files, Windows Sandbox is Pro-only, Docker = WSL underneath anyway).
      Implemented as: `wsl_probe()`/`wsl_wrap()`/`win_to_wsl()` in sandbox.py,
      `run_python(backend=)` stdin-fed WSL branch in runner.py, `sandbox_backend`
      setting (auto|wsl|off) + boot warm probe in main.py, SettingsModal select
      + README "WSL (Windows only)" section. Verified: harness 14/14 on real WSL
      + 7/7 failpaths + in-app e2e (qwen3.5:0.8b tool block: uid 65534, cwd
      /work, no /mnt, net blocked, write-back hit the active project on
      Windows). Full account: `session-log.md` 2026-10-16 close-out.
- [ ] GitHub releases: **v0.3.2** (+ optional v0.2.0 fallback), `packaging/output/` to .gitignore — installer REBUILT on the Windows box 2026-10-15 (v0.3.2, ProductVersion 0.3.2, SHA256 in session-log.md); remaining: upload release + checksums + terminal-styled landing page wired to `releases/latest/download/Su1ra-setup-x64.exe`

## Parked / someday
- [ ] **Video import (Tier 3 of file-import)** — ON HOLD 2026-10-13, awaiting use case.
      A vision model sees images, not video, so something must convert video → images.
      Options discussed (best last):
        - Frame extraction via ffmpeg (N evenly-spaced frames) — easiest, weakest.
        - Scene-change detection via ffmpeg (`select='gt(scene,0.4)'`) — fewer, more
          meaningful frames; same dependency as above.
        - Audio transcription (whisper) — often the BEST for real content (lectures,
          talks): the substance is spoken, and text is cheaper on context than frames.
          Heavier dep (model download, Windows packaging risk).
        - Hybrid (recommended when we pick it up): transcript + scene frames, with
          graceful fallback (no audio → frames only; no ffmpeg → clear message).
      Open questions before building: what are the videos (lecture? clip? screen
      recording?), are they mostly silent, and is a whisper model acceptable?
      Suggested first step: ffmpeg layer only (frames + scene detection), add
      transcription later if the use case warrants.
- [ ] Custom frameless chrome revisit (newer pywebview or different shell)
- [ ] Delayed taskbar-icon set (dropped during frameless work)
- [x] Real `.pptx` generation path — shipped as the `build_pptx` tool (structured outline → python-pptx deck + self-contained HTML slide player in the artifact pane), 2026-10-13
