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
- [ ] **WSL sandbox backend for Windows tool runs** — plan agreed 2026-10-15, build later.
      Full task doc: `sandbox-wsl-task.md` (design + acceptance checklist). Decision of
      record from the Windows option sweep:
    - Why WSL and NOT a Windows-native sandbox:
        - AppContainer / restricted token: blocks WRITE-up but an AppContainer
          process can still READ user files (Documents stays visible) — wrong for
          our threat (model code must not reach the workspace/home).
        - Windows Sandbox (.wsb): Pro/Enterprise only, no programmatic API, cold VM
          boot per run, python must be installed into a VM that resets every launch.
        - Hyper-V VM: same class, heavier still.
        - Job Objects: lifecycle + resource limits, NOT isolation (already used for
          kill-on-close; orthogonal).
        - Sandboxie-Plus: works, but bundling a third-party kernel driver = audit +
          trust burden not worth it.
        - Docker on Windows: its backend IS WSL2/Hyper-V — strictly heavier than
          using WSL directly.
      WSL2 + bwrap wins: the hard part already exists — sandbox.wrap() argv
      (unshare-net/pid/ipc, tmpfs over home, ro-binds, writable scratch) is live
      and verified on the Linux daily driver. Tighter than that setup too: the
      script runs in the WSL filesystem where the Windows home is never mounted.
    - Design: `sandbox_backend` setting ∈ `auto | bwrap | wsl | off` (default
      auto: bwrap on Linux; wsl on Windows when WSL + distro + bwrap + python3 all
      probe OK; else unsandboxed + loud label). Selector in SettingsModal next to
      the existing sandbox_tools toggle. Model-facing contract UNCHANGED — same
      run_python tool; result's `sandbox` field reports `wsl` instead of `on`.
    - Execution shape: `wsl.exe -e bwrap <same wrap() argv>`. The script is COPIED
      into the distro fs (`~/.su1ra_sandbox/<run>/`) — never run from /mnt (drvfs
      is slow + permission-quirky). stdout/stderr/exit returned normally; files the
      run creates are copied back to .scratch (tar stream) so the model can open
      them. Windows venv python CANNOT run inside WSL — the distro needs its own
      python3 (probe + first-use helper text: `sudo pacman -S python bwrap`).
    - Probe chain (cheap, cache the result): `wsl.exe --status` → distro present →
      `wsl -e which bwrap` → `wsl -e python3 --version`. Any miss → fallback:
      unsandboxed + reason in the tool-block label + log. Never crash, never fake
      containment. Gotcha: wsl.exe stdout is UTF-16 — strip nulls before parsing.
    - Scope guard: the editor's run button stays user-initiated and unsandboxed
      (same philosophy as "the user deletes" — the user pressed it). Only
      model-driven run_python tool calls route through the sandbox.
    - Acceptance (full list in task doc): settings round-trip; live checks — net
      blocked, Windows home hidden, scratch writable, output/exit correct; no-WSL
      path = loud label; Linux bwrap path regression-tested (net blocked,
      home-write no-trace); app must start fine with no WSL at all.
    - Machine status (Windows boot, 2026-10-15): WSL2 + Arch distro PRESENT;
      `python3` and `bwrap` not yet installed in the distro — one
      `sudo pacman -S python bwrap` makes this box live-testable.
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
