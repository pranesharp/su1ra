# AGENTS.md — Su1ra v0.3.1

Local-first, terminal-styled desktop chat app for Ollama models. Everything runs on
the user's machine: React+Vite frontend, FastAPI backend (:8000), pywebview desktop
shell (`desktop.py`). This file carries project context across machines/sessions —
keep it current. (Rebuilt 2026-10-13 from git history + report/report/session-log.md.)

## Layout

- `backend/main.py` — all routes: chat streaming (NDJSON), strict code-mode tool
  gating, IDE `/api/run`, settings GET/PATCH, engine endpoints, ollama setup/start
- `backend/ollama.py` — Ollama client; capability detection via /api/show;
  `friendly_load_error`; Job Object kill-on-close for spawned servers (Windows);
  child-reap by parent PID; posix killpg path
- `backend/ollama_setup.py` — first-run engine installer (download/extract/spawn);
  close mkstemp fds immediately (WinError 32), sweep stale `*.download`, 90s
  no-data stall watchdog
- `backend/puller.py` — model-pull proxy (NDJSON progress, cancel, disk-space guard)
- `backend/workspace.py` — code-mode file tools; boundary = workspace root
  (default `~/Documents/su1ra_projects`); `safe_join` (resolve + symlinks) or deny;
  ls/read/write/edit/mkdir; **deliberately NO delete/rename tool — the model creates,
  the user deletes**
- `backend/runner.py` — tool-run executor (30s timeout, 2000-line/1MB caps)
- `backend/sandbox.py` — bubblewrap wrapper for tool runs (Linux only)
- `backend/ptyrunner.py` — real PTY for the IDE output terminal
- `backend/store.py` — SQLite; `PROMPT_FILENAME = "sysp.txt"` seeds
  `default_system_prompt` (with `default_system_prompt_bundled` guard so replacing
  sysp.txt re-seeds without wiping chats); `DATA_DIR` frozen-mode aware
- `frontend/src/App.jsx` — command console, mode/loadout state, stream routing
  (streamTargetRef — deltas target the streaming assistant BY ID; onTool attaches
  by role), background model eviction (`unloadInBackground`)
- `frontend/src/components/` — ChatView (markdown+math, user msg copy/edit/redo),
  IdePane (xterm.js), ArtifactPane (sandboxed iframe; shows file path in workspace
  mode), ModelHub (catalog), OllamaSetup (first-run callout + troubleshooting
  bridge), SettingsModal (autosave), TitleBar (floating window controls — auto-hides
  without js_api), theme.js
- `frontend/src/clip.js` — clipboard helper (navigator.clipboard → textarea fallback)
- `sysp.txt` — BUNDLED artifact-generation system prompt ("The Editorialist-Engineer").
  SACRED: do not rewrite. Code-mode file-workflow rules live in the appended backend
  directive, never in sysp.txt.
- `frontend/dist/` is NOT committed — build before `desktop.py` after a fresh clone

## Modes & loadouts (core V2 concept)

- **casual** vs **code** mode. Per-mode loadout: model, context length, think
  on/off, system prompt (code mode appends the file-workflow directive).
- `/modes` prints mode + effective model + ctx/think/tools/sysprompt/engine.
  Header shows `· casual/code · model: ... · think: ...`.
- Startup boots to a fresh **casual** desk (no chat auto-opened; history in /chats).
- Switching modes unloads the other loadout's resident model via
  `POST /api/models/unload` (keep_alive: 0) — **fire-and-forget in background**
  (`unloadInBackground`), only when models differ, never on /newchat/boot.
  Optimistic UI first (mode switch must never await eviction).
- `/casual` exits code mode (shared `leaveCodeMode` path with /code-off).

## /code mode + workspace

- Tools offered ONLY when `body.tools and body.code_mode` — **strict server-side
  gating**; the old ```python auto-arm in casual was removed.
- 5 workspace tools registered (ws_ls/ws_read/ws_write/ws_edit/ws_mkdir);
  `run_python` cwd = active project dir.
- Auto-context injection: live project listing (60 cap) + a mandatory "call
  ws_ls/ws_read first" trigger sentence appended to sys_prompt every code-mode turn;
  no-project case injects /mkdir+/cd guidance instead. Best-effort, never breaks
  the turn.
- `/mkdir <name>` + `/cd <name>` commands; `workspace_root` + `active_project` in
  settings GET/PATCH with validation; `/api/workspace/mkdir|read|ls`.
- Model `.html` writes/edits in workspace mode auto-open/refresh the artifact
  preview with a `// preview:` line.
- Out-of-bounds ops = hard deny + the model explains in text. Approval popup is a
  parked v2 idea.

## /web browser pane (right split pane)

- `/web <url|query>` opens a lightweight browser in the right pane (ArtifactPane
  browser mode): URL bar, back/fwd/refresh, engine picker (default Bing), badge
  (`✓ html` / `✗ js` / `✗ blocked`), `[ open externally ]`, `[ summarize page ]`.
  No search API/scraping — all of that was deleted.
- **Link clicks → pane (GTK):** result links are `target="_blank"`. pywebview's own
  `decide-policy` handler (`gtk.py` `on_navigation`) runs first and would
  `load_url` the main webview (replacing the app). `desktop.py`
  `_install_new_window_handler` DISCONNECTS it (`disconnect_by_func`) and installs
  one wrapper: `_blank` → `window.__su1raOpenInPane(url)` + `decision.ignore()`;
  everything else delegated to pywebview's `on_navigation`. Install-once guard
  (`wv._su1ra_pane_nav`) — `events.loaded` fires for splash AND app. Iframe sandbox
  MUST keep `allow-popups` (it carries the URL; without it WebKit sends about:blank).
- **Bing redirects:** results are `bing.com/ck/a?...&u=a1<base64url>`;
  `unwrapRedirect()` (App.jsx) decodes them in `browserNavigate` and
  `__su1raOpenInPane`, otherwise the backend fetches a JS stub → `✗ js`.
- **Summarize:** `/api/page/summarize` returns page text (~12k cap);
  `conversation_id` is optional (null on a fresh boot with no chat — was a 422).
  Frontend sends it via normal `send()` (creates chat + loads model). ChatView
  renders these messages as `// summarize page: <title>` (`PAGE_SUMMARY_RE`,
  display-only; full text stored/sent; no `[ edit ]`).
- Known limits: in-iframe navigation isn't tracked (summarize uses the last
  pane-level URL); Google/Brave/DDG refuse framing.
- **Pane divider drag:** `onPointerDown` (NOT onMouseDown — pointer capture needs a
  pointerId), `body.pane-resizing` disables iframe/pane pointer events during drag,
  width clamped to `[280, min(1200, innerWidth - 360)]`.

## Settings (autosave — no Save/Cancel)

- Text inputs debounced 500ms; dropdowns/swatches/toggles save instantly
  (`commitNow`); flush-on-unmount; `/settings` gated on boot completion.
- Defaults (`default_system_prompt` / `default_temperature` /
  `default_context_length`) persist in the settings store; new conversations inherit
  them. Do NOT create conversations with `{model}` only — that was the original bug.
- Engine selector: Auto/CPU/GPU + Vulkan checkbox, live detection (`GET /api/gpu`:
  nvidia-smi, vulkan loader, adapter names), env preview, `[ restart server ]`
  (`POST /api/ollama/restart` refuses foreign servers). `ensure_running` applies
  `engine_env()` to spawned servers.
- Settings modal shows the EFFECTIVE system prompt (per-chat else global default).
- Session-scoped (reset at every app start): `show_stats`, `ide_open`. Everything
  else (accent, brightness, ide_width, ollama_url, sandbox_tools, loadout_*,
  workspace_root, defaults) persists.
- Loadout persistence had a real bug (picks never reached backend; fixed via
  autosave) — retest pending.

## Failure UX

- OOM chat errors → friendly "model too large for this machine's memory" (match
  killed/oom in Ollama's body).
- Model-hub pulls check server-side free disk (Ollama models dir — `~/.ollama/models`
  default, `%OLLAMA_MODELS%` override) against 1.1× size on the first progress
  event; cancel upstream if short. `/api/disk` powers the hub header readout.
- Ollama install: 25s client watchdog, 90s backend stall watchdog — 0%-forever is
  impossible by construction. On failure: animated "troubleshooting..." bridge that
  re-checks state (extraction usually succeeded → recovers to `[ start ollama ]`
  with zero re-download), then one auto-retry. Splash give-up is 240s (cold boot
  after install can exceed 60s).
- Post-install status staleness: setup box resolves App on any observed server
  running-edge; `refreshStatus` also reloads models.

## Platform notes — Windows

- Spawned ollama servers go in a **kill-on-close Job Object** (exact 144-byte
  extended-limit struct — basic class rejects with err 87) + scoped child-reap;
  closes the llama-server.exe orphan/leak class. Linux: killpg.
- `/eject` also kills `llama-server.exe`.
- pywebview **frameless chrome is PARKED**: flaky WinForms init race in pywebview
  6.2.1 (app hang, black window, intermittent — bisected clean at every step).
  Do not retry without a newer pywebview or different shell. Mitigations that stay:
  splash self-navigates via JS poller (never `load_url`/`evaluate_js` from worker
  threads), `PostMessage` for the icon.
- Theme flash fix: `serve_index()` stamps `window.__SU1RA_THEME__` into served
  index.html; `theme.js` seeds from it — first paint uses saved accent/brightness.
- Data: `%APPDATA%\su1ra\app.db` (Linux: `~/.local/share/su1ra/`).

## CSS gotchas (hit before)

- `.modal input { width: 100% }` out-specifies single-class rules — any new input
  inside the modal needs a `.modal`-scoped override or it stretches and crushes
  flex siblings (broke the ctx slider once; commit 0d65371).
- `.gitattributes` marks `yarn.lock` linguist-generated.

## Command surface

/help · /models (+ `pull <name>`, `get [query]`) · /chats · /delchat (<n|id>, `all`
wipes everything) · /clear (current chat messages only, chat + settings kept) ·
/newchat · /code (toggle; `<msg>` one-shot) · /casual · /modes · /mkdir · /cd ·
/settings · /stats · /ide · /eject · /connect · /web <url|query>

## History semantics

- User messages render copy / edit / redo; edit + redo truncate via
  `DELETE /api/messages/{id}/following` then resend. Chat stream emits real
  `user_id` (first event) and `assistant_id` (done event) — UI must target DB ids.
- Artifact HTML block extraction is tolerant (unclosed fence, case-insensitive);
  open/download buttons render only when extraction succeeds (commit 5100c13).

## Models seen in the wild

- Linux daily driver: `ornith-1.5:9b` (ollama library; qwen35 base, 9B, 262k ctx,
  Q4_K_M; tools/thinking/vision — native tool calls work well). `deepseek-r1:1.5b`
  never emits tool_calls (content-fallback path). qwen2.5-coder:7b was removed.
- Windows box holds: Qwen3.8-9b/4bD, gemma4:e4b, qwen3.5:4b.

## Build / run

- From source: `python -m venv .venv` → `pip install -r backend/requirements.txt`
  (+ pyinstaller for packaging) → `cd frontend && npm|yarn install && build` →
  `.venv/bin/python desktop.py` (Windows: `.venv\Scripts\`).
- **Both `package-lock.json` and `yarn.lock` are tracked — pick one** (README still
  says yarn; user moved toward npm).
- Dev loop: `uvicorn main:app` in backend/ + dev server in frontend/. Backend serves
  the built UI itself on :8000 — the reliable way to click through.
- Windows installer: `packaging\build-windows.bat` (ISCC falls back to per-user Inno
  path) + `su1ra.iss` → `packaging/output/Su1ra-setup-x64.exe`. Bundle: dist, ico,
  svg, sysp.txt. The exe is tracked in git BY USER CHOICE (rebuilds add ~19 MB each
  to history — revisit if the repo balloons).
- Distribution: github.com/pranesharp/su1ra (public), tag v0.2.0 pushed. Pending:
  v0.3.0 release + SHA256 checksums + terminal-styled landing page wired to
  `releases/latest/download/Su1ra-setup-x64.exe`.

## Parked / someday (from report/report/fplan.md)

- In-chat allow/disallow popup for out-of-bounds ops (pausable agentic loop)
- /mkdir scaffolding contents · history-stripping of superseded artifacts ·
  preview scroll/slide-state preservation · WSL execution backend toggle ·
  frameless chrome revisit · real .pptx path (python-pptx)
