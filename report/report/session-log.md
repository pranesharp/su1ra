# Su1ra work session — 2026-10-06 → 10-07

## Shipped this session (all in working tree, uncommitted)

1. **Startup = fresh casual desk** (`frontend/src/App.jsx` boot)
   - No chat auto-opened; history stays in `/chats`. Casual loadout preselected.
   - `/casual` command (shared `leaveCodeMode` path with `/code`-off).
   - `/modes` command: mode + effective model (both loadouts) + ctx/think/tools/sysprompt/engine.
   - Header shows `· casual/code · model: … · think: …`.
2. **Settings autosave** (`SettingsModal.jsx`, `App.jsx saveSettings`)
   - No Save/Cancel. Text inputs debounced 500ms; dropdowns/swatches/toggles/checkbox save instantly (`commitNow`) so closing the window can't lose picks.
   - Flush-on-unmount for pending saves. `/settings` gated on boot completion.
3. **Loadout persistence investigation**
   - DB had zero `loadout_*` keys → picks never reached backend (pre-fix close-cancel + resync-wipe, both removed).
   - Retest pending: pick models → check `/api/settings` → restart → re-check.
4. **Light mode** (`theme.js`, `IdePane.jsx`)
   - Brightness 115→140 crossfades dark palette to warm paper + flips text vars; `data-mode` on `<html>`; xterm follows via observer. Verified in node.
5. **`/eject` kills `llama-server.exe` too** (`backend/main.py`); friendly load-failure errors (`backend/ollama.py friendly_load_error`, verified against the real 500 text).
6. **Unload-on-mode-switch** (`POST /api/models/unload` via `keep_alive: 0`, verified live)
   - Only when loadout models differ, only on mode switches (never `/newchat`/boot). Confirmation line shows `· unloaded <model>`.
7. **Onboarding**: extraction hint in `OllamaSetup` (accent), empty-home new-user line, post-install next-steps panel, `/connect` next-steps append.
8. **Engine selector** (`/settings`, after pull-models)
   - Auto / CPU / GPU + Vulkan checkbox (Intel/XPU, experimental) + live detection (`GET /api/gpu`: nvidia-smi, vulkan loader, adapter names) + env preview + `[ restart server ]` (`POST /api/ollama/restart`, refuses foreign servers with instructions).
   - This box: no CUDA, Vulkan present, `Intel(R) Graphics` → env `OLLAMA_IGPU_ENABLE=1 OLLAMA_VULKAN=1`.
   - `ensure_running` applies `engine_env()` to spawned servers. `/modes` shows engine.

## Verification done
- Backend round-trips via ASGI scripts (settings/PATCH/GET, bg persist, engine validation 422, unload 200/false, OOM mapping): all pass.
- `theme.js` blend math in node: identity@100, 0→black, full paper@140.
- Every installer verified by grepping the bundled JS for feature strings.
- Installers in `packaging/output/Su1ra-setup-x64.exe` (latest 4:40 AM; earlier 8:49 PM, 9:05/9:14 PM, 3:20/3:58/4:18/4:26/4:30 AM).

## Open / parked
- Brightness-slider "stopped working" report: backend + bundle verified fine; waiting on symptom detail (drag vs persist vs missing).
- Loadout retest (above) + sysp retest in fresh casual chat.
- Pre-existing chats carry baked `think:'off'` (test think behavior on new chats).
- `report/` (this file, screenshots) is untracked — delete or gitignore before committing; it does NOT ship in the installer (only `frontend/dist`, ico, svg, sysp.txt are bundled).

## Key paths
- DB: `%APPDATA%\su1ra\app.db` · UI dist: `frontend/dist` · Installer: `packaging/output/Su1ra-setup-x64.exe`
- Run from source: `.venv\Scripts\python desktop.py` · Dev loop: `uvicorn main:app` (backend/) + `yarn dev` (frontend/, http://localhost:5173)

---

# Su1ra work session — 2026-10-08 → 10-09 (frameless, theme flash, llama leak, workspace v1, 0.3.0)

## Custom window border — attempted, bisected, REVERTED
- Goal: frameless + own 1px border + header-embedded min/max/close (`WindowApi` over js_api, `TitleBar.jsx` controls, `.window` border CSS, hwnd `WS_THICKFRAME` re-add for edge-resize).
- Result: intermittent black window + "not responding", 5x Application Hang in event log. Window sometimes never created (zero hwnds, backend fine).
- Bisect (all in `%TEMP%/opencode`, app untouched): probe v1 bare frameless OK, v2 (+min_size/big window/4-method api/fetch poller/import storm) OK, v3 (+real running uvicorn) OK. No deterministic trigger — flaky race in pywebview 6.2.1 (latest, no upgrade available) WinForms frameless init on this machine.
- Mitigations tried first (kept, all good hygiene): splash self-navigates via JS poller (no `load_url`/`evaluate_js` from worker threads), `PostMessage` icon (was `SendMessage`), resize-hack thread removed.
- Reverted to native frame; `WindowApi`/frameless scaffolding removed, notes left in `desktop.py`. `WindowControls` auto-hides without js_api (gates on `api.minimize` presence). Custom chrome parked until newer pywebview or different shell.

## Theme flash on startup — FIXED
- Cause: React booted hardcoded crimson/100/100, applied saved values only after 4 boot fetches. User DB: teal `#14b8a6`, brightness 0, contrast 150 — very visible flash.
- Fix: `serve_index()` in `backend/main.py` stamps `window.__SU1RA_THEME__` into served `index.html`; `readInjectedTheme()` in `theme.js` seeds initial state. First paint is already correct. Verified against real DB output.

## llama-server.exe leak on close — FIXED (proven live)
- Cause: `stop_spawned()` killed only `ollama serve` parent; Windows orphans `llama-server.exe` workers (3.3 GB seen). Crash-orphans then made later sessions skip cleanup ("already running").
- Fix (`backend/ollama.py`): spawned servers go in a kill-on-close Job Object (exact 144-byte extended-limit struct — basic class rejected with err 87), plus scoped child-reap by parent PID after terminate, plus posix killpg path.
- Validated: grandchild survived parent death with job open, died on job close, zero strays. No llama-server running now.

## Workspace v1 (code mode file work) — BUILT, needs restart to test
- `backend/workspace.py` (new): root boundary (`~/Documents/su1ra_projects` default) + `safe_join` (resolve+symlinks), `ls/read/write/edit/mkdir`, root-relative mkdir/cd, project-relative file tools. NO delete tool by design. 19/19 boundary tests pass.
- `main.py`: 5 tools in kit, **strict code-mode gating** server-side (`body.tools and body.code_mode`; \`\`\`python auto-arm in casual removed), run_python cwd = project dir, `workspace_root`/`active_project` in settings GET/PATCH + validation, `/api/workspace/mkdir|read|ls`.
- Frontend: `/mkdir` + `/cd` commands, workspace root field in settings (commits on blur/Enter only), active-project display, `/modes` shows root/project, artifact pane shows file path + keeps tab on refresh, model `.html` writes/edits auto-open/refresh preview with `// preview:` line.
- `sysp.txt` untouched (sacred); file-workflow rules live only in appended code-mode directive. Out-of-bounds = hard deny + ask-in-text (approval popup deferred to v2).

## Backups + releases
- `su1ra_backup2/`: fresh source-only duplicate (147 files; no .venv/node_modules/3.25GB ollama/dist/report/pycache; incl .git + setup exe). Old `su1ra - lastbestbackup` renamed to `backup2/`.
- `Su1ra.lnk` shortcut created (pythonw, absolute paths, su1ra.ico) — user moved it to final spot.
- `build-windows.bat`: ISCC falls back to per-user Inno path. Installer rebuilt.
- Version bumped **0.2.0 → 0.3.0** (UI, iss, package.json/lock); installer rebuilt with it (18.3 MB). Release advice given (v0.3.0 + optional v0.2.0 fallback as GH release assets, `packaging/output/` to .gitignore) — awaiting user go.

## Open / parked
- Workspace live test pending restart: `/mkdir laplace-deck` → `/cd` → `/code` → deck as index.html; watch anchor-miss retries + one-line confirmations.
- Approval popup (v2), `/mkdir` scaffolding contents, history-stripping of superseded artifacts, preview slide-state preservation.
- Rewrite-vs-patch: sysprompt still mandates full re-emit for chat artifacts; workspace files edit in place. Revisit if anchor hit-rate disappoints.
- Ollama binary not on PATH (logs); user installs via in-app setup. `ollama/` 3.25 GB dir present in repo (gitignored).

## In-app ollama install failure (WinError 32) + setup UX — FIXED
- Root cause: `tempfile.mkstemp` fd never closed → leaked handle locked the `.download` file on Windows → cleanup `unlink` died with WinError 32, failing an otherwise good install (and orphaning a 0-byte `llama-server.exe` earlier). Proven from the exact error path, not guessed.
- Backend (`ollama_setup.py`): close the fd at once, best-effort unlinks, sweep stale `*.download` on each run.
- Frontend (`OllamaSetup.jsx`): failure no longer drops straight to error+button. New animated `// please wait, troubleshooting...` bridge (2.5s) that re-checks state -- extraction usually succeeded, so it often recovers to `[ start ollama ]` with zero re-download -- then auto-retries install once. Final button reads `try again -- it usually works`; error-without-binary now also gets a retry button (previously a dead end). Torture-tested with a locked archive: no-raise, files land, stale swept.

## Install stuck at 0% + post-install status lies -- DIAGNOSED + FIXED
- 0% was NOT slowness: 60 MB through the app's own httpx stack in 2.6 s (~23 MB/s); backend POST /api/ollama/install streams first progress events in ms (proven live); empty ollama/ dir + zero backend connections meant the request died silently before streaming.
- Frontend hardening (`OllamaSetup.jsx`): fresh AbortController per attempt, non-OK responses parsed and shown (old code swallowed bodies without trailing newline), 25 s client watchdog -- no response becomes an honest error, 0%-forever impossible by construction. MB counter (`x / 1468 MB (p%)`) so real slowness is visible (artifact is ~1.47 GB).
- Backend (`ollama_setup.py`): 90 s no-data stall watchdog on the download stream (old Timeout(None) waited forever).
- Post-install: backend error screen was a >30 s cold boot crossing the splash give-up -- splash retries bumped 120 to 240 (60 s). `[offline]` badge lying stale after background ollama start: setup box now resolves App on server rising edge (first fix missed null-to-true; corrected to fire on any observation of running). Same staleness family in model list: `refreshStatus` now reloads models too (server holds Qwen3.8-9b/4bD, gemma4:e4b, qwen3.5:4b; boot-time empty list stuck in loadouts).
- Sysprompt "not applied" was a display gap: DB holds full 9817-char default and all recent chats carry it -- but /settings showed an empty per-chat box. Modal now shows the EFFECTIVE prompt (per-chat else global default) with a labeled note. sysp.txt untouched.
- Installer rebuilt twice more (2:24, 2:52 AM) with all of the above; bundle contents verified by string greps each time. Rebuilt again 4:08 AM with auto-context.

## /code mode-switch pause -- FIXED
- Cause: the switch awaited model eviction FIRST (POST /api/models/unload, 60 s server timeout; evicting a resident 4-9b model on a pressured 16 GB iGPU box takes seconds+), then SQLite writes, with the only user-visible line dead last. Serial awaits + slowest-first + silence.
- Fix (App.jsx): optimistic switch -- codeArmed + confirmation line land instantly, fast local writes stay awaited, new unloadInBackground() fire-and-forget eviction reporting `// freed <model> from memory` only on success. Same for /casual exit. Idempotent, rapid-toggle safe.

## Stream-token hijack via positional updates -- FIXED
- Cause: stream deltas/stats appended to whatever message sat last. A mid-stream system line (the new background `// freed` note, also `// running tool` lines) hijacked following tokens into the wrong bubble, gluing text mid-line and breaking think-tag parsing (raw tags + stray copy box in the screenshot).
- Fix (App.jsx): new streamTargetRef -- deltas/stats target the streaming assistant message BY ID across done-remap and post-tool bubbles, ref cleared on finish; onTool attaches to last assistant BY ROLE. Whole bug class closed, not just the one line.

## Auto-context listing injection -- BUILT
- Cause of "I can't see your files" refusals in /code: tools were offered (Qwen3.8-4bD advertises them, verified live) but the directive was advisory and the model had never seen the directory -- prior won on a 4b. Screenshot showed zero tool attempts.
- Fix (main.py chat endpoint, code-mode only): live project listing (top-level, 60 cap, "+N more") appended to sys_prompt every turn, plus mandatory trigger sentence (MUST call ws_ls/ws_read first; greetings need no tools). No-project case injects a /mkdir+/cd guidance line instead. Best-effort, never breaks the turn. sysp.txt untouched. Verified: compiles, format shape good, block present.

---

# Su1ra work session — 2026-10-13 (image import, Tier 1)

## Shipped this session (working tree, uncommitted)

**Image import (Tier 1 of the file-import feature).** Attach images to a chat
message so a vision model can see them. Full design + checklist in
`image-import-task.md`.

- Backend: `attachments` table (files on disk under `DATA_DIR/attachments/`,
  DB holds the reference + per-conversation `idx`); `POST /api/attachments`
  (base64 JSON), `GET /api/attachments/{id}`, `GET /api/model/caps`
  (`{tools, vision}`); `ChatRequest.attachment_ids`; chat handler base64s the
  images into Ollama's `images` field and prefixes `[image N]` labels.
- `ollama.model_supports_vision` (mirrors `model_supports_tools`).
- Frontend: `[+]` button (vision-gated), drag-drop + paste, thumbnail chips
  above the composer with `[image N]` headings, thumbnails in the user bubble.
- Per-conversation numbering restarts at 1; conversation delete/clear/message
  truncation unlink the files.

## Decisions
- Storage: files on disk + DB reference (no DB bloat, files survive revisits).
- Numbering: per-conversation `img N`, label injected into message text.
- Context: inline always (images go to Ollama natively).
- No new Python deps: switched upload from multipart to base64 JSON because
  `python-multipart` isn't installed and would be a new dependency.

## Verification done
- Backend end-to-end via ASGI TestClient with a stubbed `stream_chat`:
  upload → serve → chat (2 images, labeled content) → persistence → numbering
  restart in a new conversation → file cleanup on conversation delete → non-image
  rejected (415). All pass.
- Frontend `yarn build` clean; backend `ast.parse` clean.

## Not verified (user will do)
- Live UI click-through via `desktop.py` (real vision model, real drag-drop).
- Windows boot parity (deferred by user).

## Deferred (Tier 2/3, discussed)
- Documents: PDF / Word / text / code (pure-Python parsers; inline-with-cap vs.
  retrieval-tool decision pending).
- Video: `extract_frames` tool needing ffmpeg (packaging/support risk on Windows).

---

# Su1ra work session — 2026-10-13 (document import, Tier 2)

## Shipped this session (working tree, uncommitted)

**Document import (Tier 2).** Attach PDF / Word / PowerPoint / Excel / CSV /
text / code files to a chat. Full design + checklist in
`document-import-task.md`.

- New `backend/documents.py`: `extract()` for pdf (pypdf), docx (python-docx),
  pptx (python-pptx), xlsx (openpyxl), and a generic text path for everything
  else. Lazy imports; 400k-char cap.
- **Code files need no parser** — they are text; one generic path covers every
  language. No per-language code.
- Hybrid context: ≤8k chars inlined under a `--- [doc N] ---` header; longer
  docs deferred to a new `read_document` tool (code mode) with offset/limit.
- `attachments` table gains `kind`/`text`/`meta` (+ migration); per-kind idx so
  `[image N]` and `[doc N]` never mix.
- Composer `[+]` now fades in `[ img | doc ]` SVG buttons; image option only
  when the model supports vision, doc option always.
- New deps: pypdf, python-docx, python-pptx, openpyxl (all pure-Python).

## Verification done
- Backend end-to-end via TestClient with a stubbed model: text/code inline,
  docx inline, long doc deferred + `read_document` slice works, per-kind
  numbering (image 1 / doc 1 / doc 2), images+docs together, unsupported type
  415, conversation delete removes files + rows. All pass.
- Frontend `yarn build` clean; backend syntax clean.

## Not verified (user will do)
- Live UI: `[+]` fade-in, doc chips, drag-drop of a real PDF.
- `read_document` against a real tools-capable model (stub only).
- Windows parity (deferred).

## Deferred (Tier 3)
- Video: `extract_frames` tool needing ffmpeg (packaging/support risk on Windows).

---

# Su1ra work session — 2026-10-13 (drag & drop on Wayland/Hyprland)

## Problem
Drag & drop of files into the app did not work on the user's Hyprland (Wayland)
setup: dropping an image opened it full-screen (webview navigated to the file),
and dropping on the textarea inserted the file path.

## Root cause chain (found via `SU1RA_DEBUG=1` logging)
1. First attempt (bubble-phase `window` listeners) failed — `preventDefault`
   ran after the target's default action.
2. Capture-phase `document` listeners fixed the navigation, but the drop had
   `dataTransfer.types = ["text/uri-list","text/html"]` and `files = 0` —
   Wayland does not deliver the browser-standard `Files`.
3. `dataTransfer.getData('text/uri-list')` returns **empty** on WebKitGTK/
   Wayland, so the path is unreachable from the DOM.
4. pywebview's GTK backend DOES capture the real paths (`_dnd_state['paths']`),
   but forwards them to JS only by matching against `dataTransfer.files`, which
   is empty on Wayland — so they never arrive.

## Fix
- `desktop.py`: `NativeDrop` JS-API class with `takePaths()` that returns and
  clears `webview.dom._dnd_state['paths']`; `js_api=NativeDrop()` on the window;
  a DOM `drop` listener registered on load so pywebview captures paths at all.
- Frontend: drop handler tries `pywebviewFullPath` → `Files` → native
  `takePaths()` → `text/uri-list`, funneling all into `addFiles`.
- Backend: `POST /api/attachments/from-path` reads the file from disk (the
  webview cannot read a Wayland-dropped file); MIME inferred from extension.

## Status
- **VERIFIED LIVE** on Hyprland: dragging a screenshot attaches it as a chip.
- Windows/macOS unaffected (they use the `Files` path; the native hook is a
  no-op there).
- Debug logging stays behind `SU1RA_DEBUG=1` (prints to the backend terminal
  via `POST /api/client-log`).

---

# Su1ra work session — 2026-10-13 (wrap-up)

## Verified live by the user
- Images: attach via `[+]` and drag & drop (Hyprland/Wayland) — works.
- Documents: all formats import (picker + drop) — works.
- Esc-to-close-picker: removed as unnecessary (picker already closes on
  click-outside and on picking an option).

## Parked
- **Video import (Tier 3)** — put ON HOLD. Options and open questions captured
  in `fplan.md` (frame extraction / scene detection / whisper transcription /
  hybrid). Not started; awaiting the use case.

## File-import feature — final state
- Tier 1 (images): built + verified.
- Tier 2 (documents): built + verified.
- App-wide drag & drop incl. Wayland: built + verified.
- Tier 3 (video): parked.

---

# Su1ra work session — 2026-10-13 (web search)

## Built
- `backend/websearch.py` — DDG HTML scrape + custom search-API path
  (Brave/Serper/Tavily/SearXNG style JSON), `fetch_page()` with HTML→text
  strip + hard truncation, SSRF guard (blocks loopback/private/link-local/
  reserved/multicast, checks every resolved IP).
- `backend/main.py` — `POST /api/web/search`, `POST /api/web/fetch`;
  `search_api_url` / `search_api_key` in settings GET/PATCH.
- `frontend/src/App.jsx` — `/web <query>` (numbered results) and
  `/webf <n>` (fetch result #n, ask the model to summarize) command
  handlers; `lastSearchRef` (in-memory, per-conversation); settings
  load/save wiring for the two search fields.
- `frontend/src/api.js` — `webSearch`, `webFetch`.
- `frontend/src/components/SettingsModal.jsx` — "Web search" section with
  Search API URL + key inputs (autosaved like the rest).
- `backend/requirements.txt` — added `beautifulsoup4==4.15.0`.

## Design
- `/web` and `/webf` are standalone commands (Option A), not tool calls —
  so they work with any model, no tool-use support required.
- `/webf` does the fetch itself and hands the page text to the model to
  summarize; no tool round-trip.
- Search results are NOT persisted (in-memory per session, keyed by conv).

## Important finding — DDG now rate-limits scrapes
- `html.duckduckgo.com/html/` answers scripted requests with **HTTP 202**
  and a JS challenge shell (no `result__a` anchors) after the first hit.
- Fixed: `_ddg_search` now detects 202 / missing anchors and raises a clear
  `WebError` ("DuckDuckGo is rate-limiting this machine — set a search API
  URL in /settings ...") instead of silently returning an empty list.
  The empty list previously looked like "no matches" and hid the cause.
- The custom-API path is therefore the reliable option; verified against a
  local mock JSON endpoint (returns title/url/snippet correctly).

## Verified
- Settings round-trip for `search_api_url` / `search_api_key` (PATCH→GET).
- SSRF guard still blocks `http://127.0.0.1:...` on `/api/web/fetch` (502).
- Custom search API returns parsed results (mock server).
- DDG throttle now surfaces as a 502 with an actionable message.
- `yarn build` passes with the new App.jsx / api.js / SettingsModal.jsx.

## Not yet verified live
- End-to-end `/web` → `/webf` in the running app (needs `python desktop.py`).
- DDG scrape may still succeed from a fresh IP / after cooldown; the
  custom-API fallback is the dependable path.

---

# Su1ra work session — 2026-10-13 (web search captcha flow)

## Context
`/web` scrapes DuckDuckGo (the hacky no-key fallback); if the user sets a real
search API URL in /settings, that is used instead. DDG rate-limits scrapes and
serves a bot challenge (HTTP 202) instead of results.

## Built
- **Captcha detection**: `websearch.CaptchaRequired` raised on the 202/challenge
  shell; `/api/web/search` returns **409** so the frontend can react.
- **No-internet**: `websearch.NoInternet` raised on ConnectError/ConnectTimeout;
  endpoints return **503**; the command prints "no internet connection".
- **In-app prompt**: on 409 the app shows a `[ solve captcha ]` bar with the
  message "we need you to confirm you're human so we can proceed".
- **Native popup**: `desktop.py` `Su1raBridge.solveCaptcha()` opens a real
  DuckDuckGo window (DDG sends `X-Frame-Options: SAMEORIGIN`, so it CANNOT be
  embedded in the app UI — a top-level window is the only option). On close it
  reads `window.get_cookies()` and POSTs them to `/api/web/cookies`.
- **Cookie reuse**: `websearch` keeps the DDG cookies in memory and sends them
  on subsequent scrapes.
- `js_api` is now a single `Su1raBridge` object (pywebview takes one) exposing
  both `takePaths` (Wayland DnD) and `solveCaptcha`.

## Verified (backend, stubbed)
- Cookie storage + `Cookie:` header assembly ✅
- Captcha → 409 ✅ · no-internet → 503 (search and fetch) ✅
- Frontend build clean; python syntax clean ✅

## Not verified (needs the user)
- Live: `/web` with no API → if DDG challenges, the `[ solve captcha ]` bar
  appears → click → popup opens → solve → close → `/web` again passes.
- Whether the DDG clearance cookie actually unblocks the scrape (depends on DDG).

## Notes
- The scrape remains the no-key fallback; a real search API in /settings is the
  dependable path. Brave is best-supported by the response parser; Serper/Tavily/
  SearXNG are best-effort; Google's official API is not supported.
- Probe kept at `report/report/captcha-probe.py` (standalone second-window +
  get_cookies() check).

---

# Su1ra work session — 2026-10-13 (web search rework; captcha flow removed)

## What the live test proved
The captcha/cookie flow does NOT work:
- `get_cookies()` returned 0 cookies (window torn down before read; polling
  didn't help either).
- DDG's block is `anomaly.js` — a JS/fingerprint bot check, NOT a human captcha.
- Searching worked only while the browser window was open, and needed a fresh
  confirmation for EVERY query.

Conclusion: fighting DDG's bot detection is unwinnable. Removed the whole
captcha/cookie machinery (desktop.py bridge, /api/web/cookies, frontend bar).

## Also found
`/webf 1` on premierleague.com returned only 20 chars ("Skip to main content")
— the page is JS-rendered, so a plain HTTP fetch gets an empty shell. Now
detected: if extracted text < 200 chars, `/webf` reports the page is
JavaScript-rendered instead of handing the model nothing.

## New design
- **API is the real path** (unchanged: configured API wins).
- **Free scrape = best-effort fallback**, now multi-target:
  DDG → DDG Lite → Mojeek → Startpage (first that returns results wins).
- **If the API returns 429/402/403 (rate limit/quota)** → the app shows a
  `[ try free scrape ]` button; clicking re-runs the query with
  `force_scrape: true`.
- **No internet** → "no internet connection" (503).
- **All scrapers blocked** → 409 with a message pointing at the API setting.

## Verified (backend, stubbed)
- rate-limited API → 429 ✅ · force_scrape bypasses API ✅
- all scrapers blocked → 409 ✅ · JS-rendered page → 502 with clear message ✅
- Frontend build clean; python syntax clean ✅

## Not verified (needs the user)
- Whether any scrape target answers on their machine/IP (from the dev sandbox
  every target was bot-walled: Mojeek 403, Startpage no parseable results,
  searx.be "Verifying your browser", lite.DDG 202, Brave 429).
- The `[ try free scrape ]` button end-to-end.

## Honest state
The free scrape is unreliable by nature. A configured search API is the only
dependable path; the scrape is a convenience that may or may not work.

---

# Su1ra work session — 2026-10-13 (final: /web becomes an in-app browser)

## Decision
After the scrape and captcha approaches both proved unworkable, the user
replaced the whole `/web` feature with an **in-app browser pane** (Option C:
"generalish browser"). This sidesteps bot detection entirely — no API, no key,
no scraping.

## What was DELETED (all search machinery)
- `backend/websearch.py` (whole module — scrapers, custom-API search, fetch_page,
  SSRF guard). NOTE: this file was untracked in git, so it is NOT recoverable
  from git history.
- `backend/main.py`: `import websearch`, `WebSearchRequest`/`WebFetchRequest`,
  `POST /api/web/search`, `POST /api/web/fetch`, and the
  `search_api_url`/`search_api_key` settings handling (GET + PATCH).
- `frontend/src/api.js`: `webSearch`, `webFetch`.
- `frontend/src/App.jsx`: the `/webf` handler, `lastSearchRef`, `scrapeOffer`
  state + bar, search settings state/props.
- `frontend/src/components/SettingsModal.jsx`: the whole "Web search" section.
- `frontend/src/index.css`: orphaned `.captcha-bar`/`.captcha-text`.

## What was ADDED
- `frontend/src/App.jsx`: `ENGINES` map (google/brave/ddg/yandex/bing) + `toUrl()`
  (URL vs query detection); browser state (`browserUrl`, `browserHistory`,
  `browserIndex`, `browserEngine` default `bing`); helpers `openBrowser`,
  `browserNavigate`, `browserBack`, `browserForward`, `browserClose`.
  `/web <arg>` → `openBrowser(toUrl(arg, engine))`; `/web` → engine home.
- `frontend/src/components/ArtifactPane.jsx`: browser view (back/forward/refresh,
  engine `<select>`, URL input, open-externally, close; sandboxed iframe;
  `.browser-note` hint) rendered when `browserUrl` is truthy. Artifact
  preview/code view preserved verbatim.
- `frontend/src/index.css`: `.browser-bar`, `.browser-engine`, `.browser-frame`,
  `.browser-note`.

## Known limitations (by design, not bugs)
- **Google / Brave / DDG block framing** (`X-Frame-Options: SAMEORIGIN` /
  `frame-ancestors 'self'`) — the pane shows a hint and `[ open externally ]`.
  Bing and Yandex frame fine, hence Bing is the default engine.
- **URL bar goes stale after in-iframe navigation** — cross-origin, the parent
  cannot read the iframe's current URL. Refresh reloads the last known URL.
- **No "AI reads the page" anymore** — `/webf` is gone. If wanted, re-add as a
  `[ send page to chat ]` button in the browser bar (would need a fetch endpoint
  back).

## Verified
- `yarn build` clean (2.44s) ✅
- `backend/main.py` parses + imports clean ✅
- Zero dangling references to the deleted symbols ✅
- Pane guard preserved so `/ide` (the python IDE fallback) still works ✅

## Not verified (needs the user)
- Live: `/web python decorators` → pane opens with Bing results; clicking a
  result loads it; `[ open externally ]` on a blocked site.

---

# Su1ra work session — 2026-10-13 (in-app browser pane)

## What was built
`/web` is now an in-app browser in the existing right-hand split pane (the one
that hosts the artifact preview and the python IDE).

- `/web <query>` → pane opens at the selected engine's results
- `/web <url>` → opens that URL directly
- Pane: URL bar, back/forward/refresh, engine picker (Google/Brave/DDG/Yandex/Bing,
  default Bing), sandboxed iframe, `[ open externally ]`.

## Page badge + summarize
- `POST /api/page/info` probes a URL (frameable? fetchable? html vs js) and drives
  a badge in the browser bar: `✓ html` / `✗ js` / `✗ blocked`.
- Blocked pages (X-Frame-Options) show a notice + `[ open externally ]` instead of
  a blank iframe.
- HTML pages get a `[ summarize page ]` button at the bottom of the pane.
  `POST /api/page/summarize` fetches the page, strips HTML (BeautifulSoup), caps at
  12k chars, and returns the text; the frontend injects it as a user message and
  the model summarizes. JS-shell pages (e.g. reddit.com) → 502 with a clear message.

## Deleted (dead ends from earlier in the session)
- `backend/websearch.py` (DDG/multi-target scraping), `/api/web/search`,
  `/api/web/fetch`, `/api/web/cookies`, the search-API settings box, `/webf`,
  and the whole captcha/cookie flow.

## Findings worth keeping
- **Most big sites block framing.** Measured: only 3 of 14 sampled sites frame
  (Wikipedia, Bing, Yandex ok; GitHub/Reddit/StackOverflow/YouTube/BBC/arXiv/NYT/
  Google/Brave/DDG all send X-Frame-Options or frame-ancestors). Hence the badge
  + `[ open externally ]` escape hatch.
- **Framing and fetchability are independent.** GitHub blocks framing but its HTML
  still yields ~9.5k chars of text, so `[ summarize page ]` works on it anyway.
  Reddit is a true JS shell → not summarizable.
- **There is no free, reliable web search API.** DDG has no official search API
  (its Instant Answer API returns empty for scripted requests and only ever gives
  topic summaries, not result links); Google/Bing/Brave/Serper/Scrapingdog/Yandex
  are all paid. This is why the search-API + scrape approach was abandoned in
  favour of the browser pane.

## Status
- Built + backend-verified (page info, summarize, JS guard, bad-url 400).
- Frontend build clean; backend syntax clean.
- Live UI verification pending (user runs desktop.py).

---

# Su1ra work session — 2026-10-13 (in-app browser: link clicks)

## Reported failures (in order)
1. `/web laplace` → Bing loads in the pane, but clicking a result opened **Firefox**.
2. After removing `allow-popups` from the iframe sandbox → **nothing opened at all**
   (not even Firefox). Reverted.
3. After setting `OPEN_EXTERNAL_LINKS_IN_BROWSER = False` → Bing still loads, but
   clicking a link **does nothing**.

## Root cause (confirmed in pywebview source, not guessed)
`webview/platforms/gtk.py` connects `decide-policy`, `load_changed`,
`drag-data-received`, `resource-load-started` — but **never connects the WebKitGTK
`create` signal**. `create` is what WebKit emits when a page requests a NEW WINDOW,
which is exactly what `target="_blank"` does — and **all Bing/Google result links
are `target="_blank"`**.

So:
- `OPEN_EXTERNAL_LINKS_IN_BROWSER = True` (default) → pywebview's `decide-policy`
  sees `_blank` → `webbrowser.open()` → **Firefox** (failure 1).
- `= False` → pywebview calls `self.load_url(uri)`, but for a sandboxed iframe the
  new-window request arrives via `create`, which nobody handles → WebKit's default
  is to do nothing → **no navigation** (failure 3).

Verified: `WebKit2.WebView` has a `create` signal (`GObject.signal_lookup` → 178),
and connecting a handler that returns `None` works.

## Fix
`desktop.py`: `_install_new_window_handler()` connects the WebView `create` signal
on `window.gui.webview` and returns `None`, telling WebKit to load the request in
the existing view. Registered on `window.events.loaded`. Prints
`[su1ra] new-window handler installed`.

Also kept: `webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False` (so the
`decide-policy` path doesn't send `_blank` to the system browser either), and the
iframe sandbox back to `allow-scripts allow-same-origin allow-forms`.

## Status
- Cause confirmed in pywebview source; handler connects successfully in isolation.
- **NOT verified live** — cannot run WebKitGTK from the agent environment. Needs a
  user run: `/web laplace` → click a result → should load in the pane.

### Follow-up: handler didn't attach (`no native webview found`)

First attempt used `window.gui.webview`, which is **not set on the GTK backend**
(`window.gui` is only assigned in `Window._initialize`, and the GTK path never
goes through it for this). Live run printed `no native webview found`.

Correct path: pywebview's GTK backend registers each view in a class-level dict —
`BrowserView.instances[window.uid] = self` (gtk.py:72), and the first window's uid
is `'master'` (`__init__.py:377`). So:

```python
from webview.platforms.gtk import BrowserView
browser = BrowserView.instances.get(window.uid)   # or any entry as fallback
browser.webview.connect("create", on_create)
```

Verified: `BrowserView.instances` is a dict; `WebKit2.WebView` has the `create`
signal; the connect call succeeds. Live verification still pending.

### Follow-up 2: handler installed, but clicks still did nothing

Live run: `[su1ra] new-window handler installed` appeared, and typing a URL into
the pane's address bar DID load the page — so the iframe and the pane are fine;
only the `_blank` click path was dead.

Cause: returning `None` from the `create` handler tells WebKit "no new view", and
WebKit then **drops the navigation** instead of reusing the current view.

Fix: read the URI off the navigation action and load it explicitly in the existing
view:

```python
def on_create(view, action):
    uri = action.get_request().get_uri()
    if uri:
        view.load_uri(uri)
    return None
```

Verified: `WebKit2.NavigationAction.get_request`, `URIRequest.get_uri` and
`WebView.load_uri` all exist. Live verification pending.

### Follow-up 3: ROOT CAUSE FOUND (probe evidence)

`report/report/link-probe.py` logs every navigation signal. With the sandbox at
`allow-scripts allow-same-origin allow-forms` (no `allow-popups`), clicking a
result produced:

```
DECIDE-POLICY  frame= None  uri= about:blank      <- URL stripped
(no CREATE at all)
```

With `allow-popups` restored:

```
DECIDE-POLICY  frame= _blank  uri= https://www.bing.com/ck/a?...wikipedia...
CREATE fired   uri= https://www.bing.com/ck/a?...wikipedia...
```

**Cause:** without `allow-popups`, WebKitGTK discards the new-window request —
the URI becomes `about:blank` and the `create` signal is never emitted. So every
`create`-based handler was dead code, which is why four attempts changed nothing.

**Fix (final):**
- iframe sandbox: `allow-scripts allow-same-origin allow-forms allow-popups`
  (restored — it is what CARRIES the URL, not what escapes to Firefox).
- `desktop.py`: `OPEN_EXTERNAL_LINKS_IN_BROWSER = False` (stops the
  `decide-policy` path from sending `_blank` to the system browser).
- `desktop.py`: `create` handler loads the URI in the existing view.

Note: Bing wraps result links in a redirect (`bing.com/ck/a?...&u=a1<base64>`),
so the pane loads the redirect URL and Bing forwards to the destination. That is
normal and works in a browser.

Verified: probe shows CREATE firing with the real URL; built bundle contains the
restored sandbox string. Live app verification pending.

### Follow-up 4: link loaded, but replaced the WHOLE app

After the sandbox fix, clicking a result loaded the page — but in the **top-level
webview**, replacing Su1ra entirely. Cause: `on_create` called
`view.load_uri(uri)`, and `view` is the MAIN WebView (the app itself), not the
pane's iframe.

Fix: don't navigate the webview at all. Hand the URL to the frontend and let it
point the pane's iframe at it.

- `desktop.py`: `on_create` now calls
  `view.evaluate_js("window.__su1raOpenInPane && window.__su1raOpenInPane(<json>)")`
  (added `_js_str` helper using `json.dumps` for safe embedding; added
  `import json`).
- `App.jsx`: `window.__su1raOpenInPane(url)` opens the pane, pushes history and
  sets `browserUrl` — same path the address bar uses.

Verified: build clean, `__su1raOpenInPane` present in the bundle, `desktop.py`
parses. Live verification pending.

### Follow-up 5: app still replaced — `create` return type

`evaluate_js` fired but the app was still replaced, because `on_create` **returned
None**. Checked the signal's real signature:

```
GObject.signal_query(signal_lookup('create', WebKit2.WebView))
  -> return type: GtkWidget
```

So `create` expects a **widget**. Returning `None` = "no widget supplied" →
WebKit falls back to its default, which navigates the main webview (replacing the
app). That is the whole bug.

Fix: return a **throwaway `WebKit2.WebView()`** that is never shown. That satisfies
the signal, suppresses the default navigation, and the URL has already been handed
to the frontend for the pane.

Verified: `WebKit2.WebView()` is a `Gtk.Widget`; `desktop.py` parses; the handler
returns `WebKit2.WebView()` and still calls `evaluate_js`. Live verification pending.

### Follow-up 6: `create` approach crashed — switched to `decide-policy`

Two errors from the `create` approach:
1. `'WebView' object has no attribute 'evaluate_js'` — that is a pywebview method;
   the raw WebKit2 WebView uses `run_javascript()`.
2. **Hard crash**: returning a bare `WebKit2.WebView()` from `create` aborts WebKit
   with `std::optional<WebCore::WindowFeatures>` assertion (core dump, app hung).

So the `create` signal is a dead end. Switched to **`decide-policy`**, which the
probe showed fires with `frame=_blank` and the real URL:

```python
def on_decide_policy(view, decision, _dtype):
    if isinstance(decision, WebKit2.NavigationPolicyDecision):
        action = decision.get_navigation_action()
        if action.get_frame_name() == "_blank":
            uri = action.get_request().get_uri()
            if uri:
                view.run_javascript("window.__su1raOpenInPane && window.__su1raOpenInPane(<json>)")
            decision.ignore()      # cancel top-level nav -> app not replaced
            return True
    return False
```

This mirrors what pywebview's own `on_navigation` does, except it routes to the
pane instead of `webbrowser.open()`.

Verified: all APIs exist (`NavigationPolicyDecision.ignore`,
`get_navigation_action`, `NavigationAction.get_frame_name/get_request`,
`URIRequest.get_uri`, `WebView.run_javascript`); `desktop.py` parses; no `create`
hook and no `WebKit2.WebView()` return remain. Live verification pending.

---

# Su1ra work session — 2026-10-13 (SESSION END — browser pane unresolved)

## Outcome
`/web` in-app browser pane: **partially working, one bug unresolved.**

Works: pane opens, search results render, address bar loads pages, badge /
`[ open externally ]` / `[ summarize page ]` all render.

Broken: **clicking a result link loads the page in the WHOLE app** (replaces
Su1ra) instead of in the pane.

## Handover
Full context, the root-cause chain, all 7 failed attempts and suggested next
debugging steps are in **`report/report/browser-pane-debug.md`** (written for the
next session). Also listed in `fplan.md` under Parked / someday.

## Key finding to carry forward
`allow-popups` in the iframe sandbox is what **carries the URL** on a
`target="_blank"` click. Without it WebKitGTK strips the URI to `about:blank` and
never emits `create`. It is NOT the flag that escapes to Firefox — that is
`OPEN_EXTERNAL_LINKS_IN_BROWSER`. (Established with `report/report/link-probe.py`.)

## Also completed this session (earlier, verified)
- Tier 1 images + Tier 2 documents + app-wide drag & drop (incl. Wayland) — built,
  user-verified.
- Esc-to-close-picker — removed as unnecessary.
- `/web` search-API + scrape + captcha machinery — removed; replaced by the pane.
- Video import (Tier 3) — parked in `fplan.md`.

---

# Su1ra work session — 2026-10-13 (late) — browser pane RESOLVED + 3 follow-ups

Verification: #1 user-verified; #2/#3 user-accepted ("great"); #4 and #5 verified
by build/TestClient only — live click-through pending user test.

## 1. Pane link clicks replaced the whole app — FIXED (user-verified)
Root cause (confirmed in pywebview source): pywebview connects its own
`decide-policy` handler (`webview/platforms/gtk.py:207`, `on_navigation`) at
window creation, so it runs BEFORE ours. For `_blank` with
`OPEN_EXTERNAL_LINKS_IN_BROWSER = False` it calls `self.load_url(uri)` — that is
what navigated the main webview. Our later `decision.ignore()` was too late.
Also `window.events.loaded` fires per page (splash, then app) → double connect.

Fix (`desktop.py` `_install_new_window_handler`): `wv.disconnect_by_func(
browser.on_navigation)`, then connect ONE wrapper: our handler handles `_blank`
(→ `window.__su1raOpenInPane(url)` + `ignore()` + `return True`), everything else
is delegated to pywebview's original `on_navigation` (downloads/response
policy keep working). Guard flag `wv._su1ra_pane_nav` → installs once.

## 2. `[ summarize page ]` hidden on Bing results (badge `✗ js`) — FIXED
Bing result links are `bing.com/ck/a?...&u=a1<base64url>` redirect wrappers. The
pane stored the wrapper; the backend fetched a 65-char JS redirect stub →
`kind: js` → no summarize button. Fix: `unwrapRedirect()` in `App.jsx` decodes
`u=a1…` to the real URL, applied in `browserNavigate` and
`window.__su1raOpenInPane`. Verified 30/30 live Bing links decode to real sites.
Known limits: in-iframe navigation (clicking links INSIDE a page) is not tracked —
summarize uses the last pane-level URL; page text truncated at ~12k chars.

## 3. Summary request message was a huge wall of text — FIXED
`ChatView.jsx` `UserMsg`: messages matching the summarize header
(`PAGE_SUMMARY_RE`) render as `// summarize page: <title>` (URL in hover title).
Display-only — full text still stored + sent to the model; applies to old history
too. `[ edit ]` hidden for these; copy/redo kept.

## 4. Summarize failed on a fresh app start ("Unprocessable Content") — FIXED (pending user test)
Not model loading: app boots with no active chat, so the button posted
`conversation_id: null` and `PageSummarizeRequest.conversation_id: int` → 422.
Fix: `conversation_id: int | None = None` (backend never used it). The text then
goes through normal `send()`, which creates the chat and loads the model like any
message. Verified with TestClient: null id → 200, 12000 chars.

## 5. Pane divider drag got stuck / pane covered the whole app — FIXED (pending user test)
Likely cause: handle used `onMouseDown`, so `e.pointerId` was undefined and
`setPointerCapture` silently failed; the pane's iframe then swallowed
move/up events → stuck drag. Fix (`App.jsx` `startResize`, `index.css`):
`onPointerDown` (capture actually works), `body.pane-resizing` class during drag
(`pointer-events: none` on iframes + `.ide-pane`, `user-select: none`,
col-resize cursor), max width clamped to `innerWidth - 360` so the chat column
can't be swallowed. Clamp applies on drag only (a saved oversized `ide_width`
persists until the next drag).

---

# Su1ra work session — 2026-10-13 (rename: /code → /build)

## What
The mode formerly known as "code" is now **build** — `/build` (toggle) and
`/build <msg>` (one-shot). Reason: the mode covers decks, docs, sheets, SVGs and
apps, not just code. Word chosen: "build" (pairs with /casual, reads naturally
in one-shot use).

## Surfaces renamed (user-visible only)
- Command `/code` → `/build` in COMMANDS (`/help` + tab-complete picker)
- Header + `/modes`: mode display `code` → `build` (`· casual/build ·`)
- All system confirmation lines (build mode: on / casual exit / modes dump)
- Settings modal: "Loadout — /build switches between these", "Build model"
  (both sections), think + sysprompt + workspace-root notes → "build mode"
- Empty-chat hint (ChatView), onboarding step 3 (OllamaSetup), composer hint
- README.md modes section + command table + workspace happy path
- AGENTS.md naming note + section titles

## Deliberately NOT renamed (no DB/API migration)
- API field `code_mode` (ChatRequest), settings keys `loadout_code_model` /
  `loadout_code_ctx`, JS identifiers `codeArmed`/`codeMode`/`leaveCodeMode`/
  `codeModel`, backend comments
- `/code` still works as a HIDDEN alias (same App.jsx handler branch, not in
  COMMANDS) so muscle memory doesn't break; not tab-completed

## Verification
- `yarn build` clean (1.67s); bundle contains new strings, zero stale
  "/code <msg> / toggle code mode / use /code" strings
- backend ast.parse clean (main.py, workspace.py)
- Live UI click-through pending (user)

## Follow-up (same day): settings panel loadout headers
- `# code` loadout title → `# build`; "Code context" → "Build context"
  (both the split grid and the stacked narrow-view variant).
- Remaining "code" in the modal is legit: the sandbox toggle ("model-run code")
  and minified helper names — nothing user-facing left.
- `yarn build` clean (1.81s).

---

# Su1ra work session — 2026-10-13 (inline SVG artifact preview + download)

## Why
Asking for an SVG rendered a raw ```svg code block with only [ copy ]. User
wants a proper in-app displayer + a save button that drops the file in
~/Downloads like every other artifact.

## What
- **Inline SVG displayer (ChatView.jsx):** a code block is treated as an SVG
  artifact when fenced ```svg, or when a bare/xml block's root is <svg
  (`isSvgBlock`). It renders a 280px preview iframe ABOVE the code
  (`svgPreviewDoc`): checkerboard canvas (shows transparency), svg scaled to
  fit via CSS. `sandbox=""` — no scripts, no same-origin, no forms. Preview +
  [ download ] are suppressed while streaming (partial svg churn).
- **[ download ] in the svg code head** → existing artifact download path
  (`downloadArtifact(code, css, js, kind)` — kind threaded through).
- **Backend /api/download:** `DownloadBody.kind` ("html" default | "svg").
  svg branch writes `su1ra-<name>.svg` in ~/Downloads with the same -2/-3
  collision numbering; sanity-checks `<svg` in first 2000 chars (422); unknown
  kinds → 422. HTML/project path untouched.

## Security note
Model-generated SVG is untrusted input: preview runs in a fully sandboxed
iframe (scripts/forms/same-origin all blocked) — event handlers inside the svg
cannot touch the app. Download writes .svg only after the root check.

## Verification
- Backend live (scratch port 8765): svg → su1ra-artifact.svg, collision →
  -2.svg, filename → su1ra-moon.svg, non-svg → 422, bad kind → 422, html path
  unchanged. Test files cleaned from ~/Downloads (user's own su1ra-artifact-3.html kept).
- `isSvgBlock` unit-checked in node: 7/7 cases (svg fence, bare <svg, xml+svg,
  xml non-svg, python, html, plain).
- `yarn build` clean; main.py parse clean.
- NOT verified live in the UI: the preview iframe rendering + [ download ]
  click-through (user runs desktop.py).

---

# Su1ra work session — 2026-10-13 (build_pptx tool: AI decks)

## Why
Build mode had no first-class way to make presentations. Model-written
python-pptx is unreliable (EMU coordinate math, overflow bugs, ~no styling
consistency). Decision (with user): approach C — dedicated structured tool +
run_python as escape hatch; preview = own lightweight HTML slide player in the
existing artifact pane (no LibreOffice, no CDN — the sandboxed iframe has no
network anyway).

## What
- **backend/pptx_builder.py (new, ~450 lines):**
  - `build_deck(outline, project_dir)` — validates a JSON outline (max 60
    slides; title/section/bullets/two_col/table/image; optional speaker notes
    per slide; "> bullet" = accent emphasis line; image paths relative to the
    project, png/jpg/gif/bmp/tiff only) then writes `<stem>.pptx` AND
    `<stem>.preview.html` into the project dir. Bad outline → OutlineError,
    tool text tells the model exactly what to fix. Missing image → warning +
    styled placeholder, never a failed deck.
  - **No-drift trick:** one THEMES + one LAYOUT_IN dict feed both renderers;
    the player stage is 960x540 so preview px == slide pt (72px/in) — sizes
    match by construction. Themes: terminal-dark (Consolas) + clean-light
    (Calibri).
  - The pptx uses the blank layout + manual textboxes, 16:9, accent rules,
    slide numbers, speaker notes via notes_slide.
  - Player: vanilla JS, ←/→/space/pgup/pgdn/home/end, click zones, prev/next
    buttons, progress bar, DECK JSON injected with `</` escaped. Images
    embedded as data URLs (iframe has no file access).
- **backend/main.py:** build_pptx registered in TOOLS (gated by the existing
  strict code-mode tool gating), dispatch branch runs it IN-PROCESS (like ws_*
  tools — no sandbox, pure python, no network), tool event reports the player
  html as `path`, format_pptx_result for the chat line, unknown-tool list
  updated, code-mode directive now says "decks → build_pptx".
- **frontend/src/App.jsx:** artifact bridge also fires on build_pptx events →
  the player auto-opens in the preview pane.
- **Docs:** AGENTS.md tool notes, fplan.md parked item ticked.

## Revision loop
Calling build_pptx again with the same filename overwrites both files in
place — "make slide 3 punchier" is one cheap tool call, no pptx surgery.

## Verification
- Builder unit-tested live: 6-slide deck (all layouts) builds; re-opened with
  python-pptx → 6 slides, 13.333x7.5in, notes present; player 10KB self-
  contained; 4 bad-outline rejections give actionable messages; missing image
  → warning + placeholder; clean-light theme + same-filename regeneration OK.
- Player inline JS: node --check passes.
- `import main` clean with TOOLS = [run_python, ws_*, read_document,
  build_pptx]; formatter output sane; `yarn build` clean (1.85s).
- NOT verified live: actual rendering in the app's WebKitGTK pane (user runs
  desktop.py). Text wrapping in the player will differ slightly from
  PowerPoint's — structure/styling match by construction.

---

# Su1ra work session — 2026-10-13 (fix: build_pptx preview did not auto-open)

## Root cause
The tool-event serializer only attached `path` for ws_* tools:
  `"path": ws_path if name.startswith("ws_") else ""`
So build_pptx ran fine (files written) but the frontend artifact bridge never
received the player path → no auto-preview. The dispatch branch DID set
ws_path = preview; the serializer dropped it.

## Fix
backend/main.py: `"path": ws_path if (name.startswith("ws_") or name == "build_pptx") else ""`
(one line). Frontend bridge + workspace/read needed no changes.

## Verification (live, in-process)
Drove the real /api/chat generator with a stubbed ollama (matching its
normalized chunk protocol: {"tool_calls": [...]}, {"done": ...}):
  tool event name=build_pptx, path='chain-test.preview.html', exit=0,
  output "[pptx ok] chain-test.pptx · 1 slide(s) ..." then
  GET /api/workspace/read?path=chain-test.preview.html → 200, 7559 chars.
Chain build_pptx → event path → bridge → player is proven.
Test artifacts + test conversations cleaned from the user's DB/Projects dir.

## User action needed
Fully quit + relaunch the app so the backend picks up the fix (dist already
rebuilt earlier — no frontend change in this fix).

---

# Su1ra work session — 2026-10-13 (fix: build_pptx kept rejecting the model)

## Symptom (screenshot)
Model thinking: "the tool keeps rejecting it... rejecting my JSON format" →
gave up and wrote a plain HTML deck instead. Tool never produced a pptx.

## Root causes (two, both real)
1. **finalize_tool_call's run_python fallback poisons other tools:** when a
   model emits tool args as a MALFORMED JSON string, finalize does
   `args = {"code": args}` — so build_pptx received {"code": "..."} with no
   slides → reject → model blames its JSON → retry loop.
2. **Validator was written for perfect JSON:** unknown layout names ("bullet"
   vs "bullets", "cover"), unknown themes ("dark", "neon"), stringified
   slides arrays, single-object slides — all hard-rejected.

## Fixes
- **main.py dispatch:** build_pptx recovers the outline from a parked
  args["code"] string (json.loads) before building.
- **pptx_builder hardening (normalize, don't reject):**
  - accepts outline as a JSON string / under outline|deck|slide_deck|
    presentation keys (incl. whole-outline objects) / parked under "code"
  - slides: array | single object | JSON-encoded string; bullets/rows/columns
    accept alias keys (points, bullet_points, items, data, col1/2,
    left/right_bullets) and JSON strings
  - layout aliases (bullet/list/points/content/text→bullets, cover/
    title_slide→title, divider/heading/chapter→section, columns/comparison/
    split→two_col, picture/photo→image); unknown layout → INFER from present
    keys + warning, never reject
  - theme aliases (dark/terminal/mono, light/bright); unknown theme → warn +
    default instead of reject
  - missing filename → derived from the first slide title
  - only truly unrecoverable input still rejects, with a teaching message
    (straight quotes, no trailing commas)

## Verification
13/13 hostile battery (incl. both root causes + the original happy path with
pptx re-open validation). backend parse + import clean. Frontend untouched —
no rebuild needed; RESTART the app to load the new backend.

---

# Su1ra work session — 2026-10-13 (activity indicator: sine wave)

## Why
During tool loops the app looks frozen — tokens stop, no visual signal until
[ stop ] flips back to [ send ]. User asked for a tiny accent sine wave above
the composer while working, gone when idle again.

## What
- Composer.jsx: `SineWave` component (72x14 svg, accent-colored sine path)
  mounted only when the existing `streaming` prop is true. That prop already
  spans the WHOLE request — token streaming AND the tool loop (setStreaming
  wraps the fetch in App.jsx) — so the wave covers quiet tool stretches too.
  Unmounts the moment [ stop ] → [ send ] flips.
- index.css: `.sine-wave` + `.sine-path` — dash-offset marching animation
  (0.9s linear, dasharray 6/4) + 1.6s breathe fade (opacity 0.55→1). Pure CSS,
  no JS timers, zero layout shift (block above the box).

## Verification
yarn build clean; class names + keyframes present in dist assets. Live look:
needs the user's restart + a running generation.

## Docs sweep (same day, v0.3.1 wrap-up)
- THIRD-PARTY-NOTICES.md: added the six backend libs shipped by the installer
  but missing from the notice (pypdf, python-docx, python-pptx, openpyxl,
  beautifulsoup4, Pillow) — requirements.txt was ahead of the notices.
- fplan.md: GitHub-releases item re-targeted to v0.3.1 + note that the exe
  must be rebuilt on Windows (PIL un-excluded from su1ra.spec for build_pptx).
- README/AGENTS verified: zero stale "/code <msg>" or "code mode" user-facing
  refs; version strings all v0.3.1.
- report/AGENTS.md (snapshot copy inside report/): header bumped to v0.3.1 for
  consistency; the LIVE agent instructions are the root AGENTS.md (this one is
  an older snapshot kept for the report trail).

---

# Su1ra work session — 2026-10-13 (dev launchers)

## What
Two double-clickable dev launchers at the repo root (user request: open dir →
make venv → use venv → run desktop.py):
- **launcher-linux.sh** (bash): cd to script dir, create .venv if missing,
  source .venv/bin/activate, pip install backend/requirements.txt + pillow on
  first run (guarded by an import probe, not a flag file), build
  frontend/dist if missing (yarn||npm), run desktop.py. On crash: exit code +
  distro-specific GTK/QT binding hint if neither `gi` nor `qtpy` imports
  (arch/debian/fedora package names) — the exact cryptic failure a fresh
  machine hits with pywebview. `PYTHON` env var overrides the interpreter.
- **launcher-win.bat** (CRLF, DOS batch): same flow — python → `py -3`
  fallback (`PYTHON=` override), .venv\Scripts\activate.bat, requirements +
  pillow, frontend build via yarn||npm, desktop.py; pause-on-error so the
  window survives crashes.

## Notes
- pillow added explicitly: build_pptx needs it (0.3.1) but it is not in
  requirements.txt (it's a pptx_builder lazy import).
- Windows file saved with CRLF line endings (cmd.exe misbehaves with LF).
- Frontend build step is a safeguard: desktop.py serves frontend/dist.

## Verification
- Linux launcher end-to-end in a disposable copy (fresh venv): venv created,
  all deps installed, desktop.py launched (only failed at GTK bindings —
  absent in the headless test sandbox, present on real machines; launcher now
  prints the fix hint for exactly that case). bash -n clean.
- win.bat: CRLF verified (od), syntax review only (no Windows here).

---

# Su1ra work session — 2026-10-13 (build_xlsx / build_docx / build_pdf)

## What
The pptx pattern extended to the other school formats. New module
**backend/doc_builders.py** (~450 lines) with the SAME contract as
pptx_builder: model sends a JSON outline, backend owns layout, writes the
real file + a self-contained `<name>.preview.html` into the project dir, and
returns {ok, path, preview, sheets|blocks, warnings}. OutlineError messages
teach the model how to fix bad input. Same normalization hardening as the
pptx fix (JSON-stringified payloads, alt keys incl. "content", parked
args["code"] recovery, alias keys, "a bare string becomes a paragraph").

- **build_xlsx** (openpyxl): sheets=[{name, rows}]; first row = styled frozen
  header (accent fill), numeric cells stay numeric, column widths auto-sized,
  31-char Excel sheet-name cap honored. Preview: sticky sheet tabs + grid.
- **build_docx** (python-docx): flat blocks list — h1/h2/p/bullets/numbers/
  table(first row=header, "Light Grid Accent 1" style)/pagebreak; title
  centered with accent rule. Preview: A4 white pages, same structure.
- **build_pdf** (reportlab, NEW dep requirements.txt reportlab==5.0.1): same
  block list; A4 platypus doc, striped tables, real PageBreak. Preview: same
  page rendering as docx.

## Wiring (main.py)
- 3 tools in TOOLS (strict code-mode gating as usual), dispatch branch runs
  them in-process with args["code"] recovery, format_doc_result for chat
  lines, directive now lists all four build_* formats.
- Tool-event serializer: `name.startswith("build_")` (future-proofs build_*).
- su1ra.spec: hiddenimports for the lazy imports (documents, pptx_builder,
  doc_builders, pypdf, docx, pptx, openpyxl, bs4, PIL, reportlab) — cheap
  insurance for the installer.
- Launchers: import probe extended (docx/openpyxl/reportlab).
- THIRD-PARTY-NOTICES: ReportLab added (Pillow + the doc libs were already
  added earlier today).

## Verification
- 15/15 unit battery (xlsx numeric cells + reopen, docx reopen w/ table text,
  pdf reopen: pagebreak → 2 pages, text extraction present; aliases,
  stringified payloads, unwraps, empty-input rejections, previews offline).
- E2E through the real chat generator (stubbed model): all three tools ran in
  the tool loop, events carried preview paths, files exist in the project dir,
  chat lines formatted. Test files + conversations cleaned.
- main.py parse + import clean; TOOLS = 11; yarn build clean.
- NOT verified live: rendering in the pane (user restart needed).

---

# Su1ra work session — 2026-10-13 (AI always starts projects in a NEW folder)

## Why
The model could dump files straight into the workspace root (or reuse whatever
project was active). User rule: the AI must ALWAYS make a new directory before
beginning a project, never write into the current directory.

## What
- **NEW tool `ws_cd`** (the model previously could not switch projects at all
  — it had to ask the user to run /mkdir + /cd). Dispatch does mkdir-if-missing
  + set_active_project atomically, so "start a project" is ONE tool call:
  ws_cd photosynthesis-deck → creates the folder if missing, switches to it,
  announces `[project: photosynthesis-deck — created]`. Existing project →
  switches with no "created". Escape attempts (../) and empty args → denied
  with the standard boundary errors. Accepts `project` or `path` arg.
- **Directive (code-mode sysprompt)**: NEW PROJECTS rule — always ws_cd a
  fresh kebab-case folder before producing files; NEVER write into the
  workspace root or reuse the current project for a different task; work in an
  existing project only when the user clearly means it ("fix my deck").
- **No-project hint** flipped: instead of telling the user to run /mkdir+/cd,
  it now tells the model to ws_cd itself.
- **Frontend**: on a successful ws_cd tool event, header project label syncs
  immediately (api.getSettings → setWorkspace) instead of going stale.
- Unknown-tool list updated; auto-context + /cd + /mkdir behavior unchanged.

## Verification
- Live dispatch tests: create+switch ("— created"), re-cd (no created),
  ../ escape denied (exit 1), empty arg denied, `path` alias accepted.
- Active project restored + test folder/conversations cleaned afterwards.
- parse + import clean; TOOLS = 12 (ws_cd added); yarn build clean.
- Restart needed (backend + frontend changed).

---

# Su1ra work session — 2026-10-13 (previews for pre-existing files: /preview)

## Why
Every build_* tool already writes <name>.preview.html (that shipped with each
tool). What was missing: previews for files NOT born from build_* — decks made
via run_python, PDFs/xlsx dropped into the project by hand.

## What
- **doc_builders.preview_existing(path)**: reads a real pptx/xlsx/docx/pdf/svg
  and renders the SAME style of <name>.preview.html next to it (pptx → slide
  headings + bullets via python-pptx text frames; xlsx → tabbed grid via
  openpyxl read_only; docx → pages via python-docx style mapping; pdf →
  per-page text via pypdf, first 60 pages; svg → checkerboard viewer).
  Normalized blocks (kind/text/items) — first draft emitted raw alias keys and
  KeyError'd in _docx_body; fixed. Unsupported ext / fake svg → OutlineError.
- **POST /api/preview {path}**: workspace.resolve boundary check (../ →
  denied), 404 on missing, 422 on unsupported.
- **/preview <file> console command** (+COMMANDS list, /help, tab-complete):
  calls the endpoint, prints `// preview: <name>.preview.html (from <src>)`,
  opens it in the artifact pane via the existing refreshFilePreview.
- api.js: previewFile().

## Verification
- 8/8 unit battery: raw pptx (title text lands in the preview), builder-made
  xlsx/docx/pdf, svg, .txt rejected, fake svg rejected, previews offline
  (no src/href remote refs — xmlns identifiers not counted).
- Endpoint live via ASGI: 200 + file written; ../ escape and missing → 422/404.
- parse + import clean; yarn build clean. Restart needed.

---

# Su1ra work session — 2026-10-15 (fix: ws_ls/ws_read/ws_write/ws_edit silently killed the stream)

## Symptom
Build mode, capable model: it calls ws_ls, the app shows "// running tool: ws_ls ...",
then the stream just ENDS — sine wave stops, [stop] flips back to [send], no error
shown anywhere. Same with ws_edit (and presumably ws_read/ws_write).

## Root cause (reproduced in-process on Windows, not guessed)
`backend/main.py` tool dispatch, ws_* branch: the `ws_ls`/`ws_read`/`ws_write`/
`ws_edit` paths assigned only `ws_res` — `result`/`result_text` were assigned ONLY
in the `ws_cd` sub-branch and the `else` (ws_mkdir) sub-branch. First tool call of
the request hits `store.add_message(..., result_text)` with `result_text` UNBOUND →
`UnboundLocalError` → the chat generator dies right after `tool_start` was yielded →
the NDJSON response closes with no error event → frontend reader sees EOF →
`onDone()` → streaming false. Silent stop, exactly as reported. (`build_*`,
`run_python`, `read_document` set both vars, which is why decks/sheets kept working.)
Regression came in with the ws_cd commit (2026-10-13): the shared
`result_text = format_ws_result(ws_res)` got scoped into the mkdir/ws_cd paths only.
The earlier E2E verified build_* + ws_cd but never ws_ls/read/write/edit through the
chat path — that's the test gap.

## Fixes (backend/main.py only; no frontend change, no rebuild of dist)
1. Generic `result`/`result_text` assignment now applies to every ws_* tool except
   ws_cd (which sets its own "[project: ...]" text): `if name != "ws_cd":`.
2. Defaults-before-dispatch: `result`/`result_text` are initialized BEFORE the
   dispatch chain ("[internal error: tool 'X' produced no result...]"). No branch
   can leave them unbound (this bug class now degrades to a visible tool error the
   model can react to, and the loop continues), and a second tool call can never
   reuse the previous call's stale result text.

## Verification
- New repro `report/report/repro-tool-loop.py` (APPDATA redirected to a temp dir —
  user's real DB/workspace untouched): drives the REAL /api/chat generator with a
  scripted two-round ollama stub across 10 cases — ws_ls (with and without args),
  ws_read, ws_edit, ws_write, ws_mkdir, ws_cd, build_pptx, read_document, unknown
  tool. ALL 10 complete the loop (tool_start + tool event + done). Before the fix,
  ws_ls died with UnboundLocalError (traceback captured).
- `ast.parse` clean; test temp dirs cleaned from %TEMP%.

## User action needed
Restart the app so the backend picks up the fix (no frontend rebuild needed).
NOTE: the freshly built Su1ra-setup-x64.exe PREDATES this fix — rebuild the
installer if the fixed build should ship.

---

# Su1ra work session — 2026-10-15 (per-mode system prompts + per-chat mode persistence)

## Ask
1. Rebuilt sysp.txt needs to re-seed — verified it happens automatically on next
   boot (stored default was pristine == marker; new 10932-char text pushes).
2. sysp.txt showed in BOTH modes' settings boxes — casual must not show/carry it;
   each mode gets its own system prompt (casual ships EMPTY by user's choice).
3. /chats: one mixed list — want BUILD and CASUAL split (left/right columns).
4. Opening an old build chat from casual must switch the mode automatically.

## Root causes
- PROMPT LEAK: frontend STAMPED the global default (sysp.txt) into every new
  conversation's per-chat system_prompt at creation (chatDefaultsRef spread),
  and SettingsModal displays per-chat-else-default -> sysp visible in casual.
  Backend only ever SENT it in build, so it was display + stored-data leak.
- NO MODE PERSISTENCE: conversations had no mode column at all — mode was
  per-request (body.code_mode) + transient frontend state, so reopening a chat
  could not restore what it was.

## Implementation
Backend:
- store.py: conversations.code_mode column (ALTER migration), _conversation_dict
  exposes it, create/update accept it. One-time normalization (guard setting
  perchat_sysp_norm): clears per-chat system_prompt stamps that are byte-equal
  to a bundled default (old marker or new text) — customs survive; backfills
  code_mode=1 for chats that produced tool messages (only build chats did).
- main.py: ConversationCreate/Update + endpoints accept code_mode;
  default_system_prompt_casual setting (GET/PATCH); chat() resolves
  per-chat override -> else mode default (build=sysp.txt, casual=casual default).
  Build still appends the tool directive + project context after it.
Frontend (App.jsx):
- createConversation calls (newChat, send lazy-create, attachment lazy-create):
  no system_prompt stamp; pass code_mode (chat tagged with birth mode).
- selectConversation: MODE FOLLOWS THE CHAT — flips codeArmed + picker model +
  new-chat ctx defaults to the target loadout (deliberately lighter than
  /build: no settings rewrite, no forced IDE open), background eviction.
- Manual /build // /casual with a chat open: retagActiveChat patches its mode.
- /chats: two monospace columns (BUILD left, CASUAL right), global ordinals
  kept so /chats <n|id> resolution is unchanged; 20-row cap with overflow note.
- /modes: sysprompt label reflects real resolution (per-chat / sysp.txt /
  casual default / off).
- saveSettings: systemPromptScope ('default'|'chat') — default edits write
  default_system_prompt (build) or default_system_prompt_casual (casual) only;
  per-chat edits patch the open chat only. No cross-stamping ever again.
- SettingsModal: mode prop + defaultSystemPromptCasual prop; shows per-chat
  override else the MODE's default; reset = bundled sysp (build) / empty
  (casual); scoped autosave payload.
- frontend rebuilt (yarn build) — served by backend on :8000.

## Verification
- report/report/repro-mode-prompts.py — 19 checks, ALL PASS (isolated APPDATA):
  casual default ships empty; build default = sysp.txt; normalization clears
  stamps + keeps customs + backfills tool-msg chats; code_mode persists through
  create/update; prompt resolution matrix (build/casual x default/override/none,
  no cross-leak); API models accept the fields.
- report/report/repro-tool-loop.py — 10/10 tool cases still pass after changes.

## User action needed
Restart the app (backend + rebuilt UI). Normalization runs once on boot: old
chats whose per-chat prompt == a bundled default are cleared; chats with tool
history retag as build. Installer predates all of today's fixes — rebuild
before shipping.

## Follow-up same day — /build and /casual now open a NEW chat in the target mode
User: switching modes stayed in the same chat, which fights the per-chat mode
model (and retagging on switch was the wrong move). New semantics:
- Mode switch (via /build toggle, /build toggle-off, /casual) = a FRESH chat on
  the new desk. The chat being left is untouched — it keeps its mode + history
  and stays in its /chats column.
- Empty current chat (no messages yet) is RETAGGED + REUSED instead of creating
  another empty shell (startModeChat) — toggling back and forth can't spam /chats.
- selectConversation still follows the chat's mode (unchanged).
- retagActiveChat removed (was dead the moment switches stopped retagging);
  applyModelCtx no longer patches the active conversation (picker + new-chat
  defaults only).
- One-shot /build <msg> unchanged (arms for one message in the current chat).
Frontend rebuilt; repro suites re-run: 19/19 mode-prompt checks + 10/10 tool
loop cases pass.

## Follow-up same day — /ide → /editor, general-purpose file-type editor
- Renamed across user surfaces: /editor command (/ide kept as hidden alias,
  /code precedent), pane title "editor", COMMANDS list, attachEditorRun label
  ("// attached: editor run — <file> (exit n)", ext-matched code fence),
  sendEditorToChat wording. Component file IdePane.jsx → EditorPane.jsx;
  state ide* → editor*. Settings keys STAY ide_open/ide_width (DB compat,
  code_mode precedent). CSS: new .ide-filename header input.
- Generalized from python-only to file-type-aware: the buffer belongs to a
  filename (editable header field, default scratch.py). Run saves the buffer
  to <DATA_DIR>/scratch/<filename> and executes THE FILE by extension —
  .py (frozen-aware python_exe(): sys.executable in the bundled exe is
  su1ra.exe, NOT python — latent bug fixed), .js/.mjs/.cjs (node), .sh/.bash,
  .ps1, .bat/.cmd, .rb, .pl, .lua. Missing interpreter or non-runnable ext
  (md/txt/json = save-only) → clean 422; frontend disables run + status hint.
  Filename sanitized (_FILENAME_RE, basename, traversal rejected).
- New POST /api/editor/file (save without run). PtySession generalized to
  (argv, cwd, env); legacy Windows path spawns argv (30s cap kept).
- Verification: report/report/repro-editor.py 11/11 PASS (py runs from file +
  __file__ semantics, node, cmd bat, md 422, traversal/subdir rejected, ruby
  missing-interp 422, save endpoint + validation); mode-prompt suite 19/19 +
  tool-loop 10/10 still green. Frontend rebuilt.

## Follow-up — html/svg in the editor: run = preview (user asked why "save only")
page.html showed "not runnable — save only": RUNNABLE only listed terminal
interpreters. Added PREVIEWABLE (html/htm/svg): run button enabled, labeled
"preview", saves + hands the buffer to the artifact pane (onPreview ->
setArtifact + preview tab, path null = buffer-backed). True non-runnable types
(md/txt/json) keep the save-only state. Frontend rebuilt.

## Follow-up — system monitor (btop-lite) in the composer foot, bottom-left
- Backend: /api/sysmon + SYSMON sampler task (started from the startup event,
  2s cadence, pure stdlib — NO psutil, frozen build unchanged). cpu =
  GetSystemTimes delta (Win) / /proc/stat delta (Linux, needs one tick);
  ram = GlobalMemoryStatusEx dwMemoryLoad (Win) / MemTotal-MemAvailable
  (/proc/meminfo); disk = shutil.disk_usage(DATA_DIR) — NOTE shutil has NO
  .percent (that's psutil) — computed used/total; gpu = nvidia-smi
  utilization (+ vram fill) discovered once in a worker thread, null when
  absent (Intel/AMD iGPU boxes get a dimmed empty bar, tooltip 'unavailable').
  Verified live on this machine: cpu 28.1 / ram 54 / disk 87 / gpu null.
- Frontend: SysMonitor.jsx polls every 2s; 2x2 grid of thin bars, each between
  literal [ ] brackets, colored fills (G gpu = --accent, M ram = --sm-green,
  D disk = --sm-amber, C cpu = --sm-blue), NO numbers on screen — real values
  in the hover tooltip only. Positioned fixed bottom-left (24px/14px); hidden
  under 1180px window width so it never collides with the centered composer.
  Rendered in Composer's new .composer-foot row (sysmon left, hint right).
- frontend rebuilt; endpoint smoke-tested via TestClient (200 + live values).

## Fix — sysmon "bars do nothing" (user report)
Diagnosis from screenshot: brackets rendered (new frontend live) but all fills
empty -> the RUNNING backend pre-dated /api/sysmon (netstat showed :8000
TIME_WAIT, no listener at check time; app closed). Frontend polls were 404ing
-> stats stayed null. Fix = full app restart. Also fixed a real bug found
while diagnosing: the sampler task was fire-and-forget create_task (no held
reference — asyncio may GC it); now start_sysmon() holds _sysmon_task.
SysMonitor now distinguishes offline (3 consecutive failed polls -> cluster
dimmed, container tooltip 'restart the app') from per-bar unavailable.
Rebuilt frontend; boot-path test (reset_session_settings -> sampler live ->
endpoint 200 with cpu/ram/disk) passes.

## Follow-up — editor v2: .scratch root + explorer + dirty/ctrl+s + CodeMirror
- Scratch root moved to ~/Documents/.scratch (user-visible, dot-prefixed app
  folder). One-time migration: legacy %APPDATA%/su1ra/scratch files COPIED
  (not moved) into the new root on first editor_root() call (process-level
  flag; skipped when root exists).
- Subfolders now first-class: _editor_rel_path validates slash paths
  ('proj/main.py', per-segment regex, ../ and . rejected, resolved-inside-root
  check), /api/run cwd = the file's PARENT dir (sibling imports work in
  projects), save creates parent dirs. rel from /api/editor/open is
  as_posix()-normalized (Windows backslashes confused the frontend test).
- New endpoints: GET /api/editor/open?path= (read into buffer, 400k cap,
  404/422 clean), GET /api/editor/tree (recursive tree, depth 5, 800 entries,
  dirs-before-files), POST /api/editor/mkdir (folders OR empty files).
- Frontend EditorPane: CodeMirror 6 (basicSetup + per-ext langs py/js/html/
  css/json/md; theme Compartment follows data-mode light/dark, transparent
  bg, mono; Mod-s keymap), external code changes dispatched into CM, custom
  gutter dropped (CM line numbers). Explorer sidebar (files toggle): tree,
  click file = open (loads content + snapshot), [+file]/[+dir] with
  collision-avoiding names. Dirty = code !== snapshot: '· unsaved' next to
  filename + in status line; ctrl+s saves (window listener + CM keymap);
  save refreshes tree. run() reads codeRef (no stale prop).
- Verification: repro-editor2.py 12/12 (migration, subpath save/open/mkdir,
  tree nesting, run-with-sibling-import + cwd, traversal still blocked);
  repro-editor.py updated for new root (11/11); mode-prompts 19/19 +
  tool-loop 10/10 green. Frontend built with CM bundles.

## Follow-up — btop-flavored editor pane + movable bottom section
- Bottom output/terminal wrapped in .ide-bottom (fixed px height, default 240):
  tinted top border (color-mix accent 38% + border), four box-drawing corner
  glyphs (┌┐└┘, absolutely positioned ON the line, panel bg masks under,
  pointer-events none), and an .ide-split drag row (label "output" punched
  into the border line + centered ··· grip; pointer capture pattern per
  AGENTS.md — onPointerDown/Move/Up/Cancel, body.pane-resizing reused to mute
  iframes). Drag up = taller; clamp [90, paneHeight-280]; xterm refits via
  existing ResizeObserver + fit effect deps now include termH.
- Pane outer border tinted accent (22% mix, right edge flush); status bar is
  an inverted-ish strip: accent 9% bg + btop-line top border + brighter text.
- build clean. (Visual: verified only structurally — user confirms on screen.)

## Follow-up — full btop panel system + accent-derived hue family
- Every section of the editor pane is now its own btop-style bordered box,
  not just the output: `.panel` class (border, relative, column flex) with
  hue modifiers `.h-a/b/c/d` that set `--ph` (panel hue); `--ph-line` is
  `color-mix(--ph 38%, border)`. Three panels in `.ide-body` + bottom:
  scratch explorer = h-b, code editor = h-a, output = h-c. Each gets a
  punched `.panel-title` (absolute, top -7px, panel bg masks the border
  line under it) and a shared `Corners()` component — ┌┐└┘ absolutely
  positioned ON the corners, panel bg padding masks the line beneath,
  pointer-events none. Title + borders + corner glyphs all take `--ph`,
  so recoloring is one custom prop per panel.
- Splitter visually merged into the top border: `.split-label` ("output")
  punched into the line like a panel title, `···` grip centered, hover
  brightens both toward --ph.
- Hue family (theme.js): `deriveHueFamily(hex)` derives an ANALOGOUS
  4-color set from any accent — --h-a IS the accent, --h-b rotates +45°,
  --h-c −50°, --h-d +105°, with saturation damped (×0.8/0.75/0.6, cap
  0.85) and lightness pulled into a readable band (0.2–0.72). HSL rotation
  implemented from scratch (hex→hsl→hex, ~15 lines) — no color lib.
  `applyAccent()` now sets all four vars, so every accent pick re-tints
  the whole panel system in-family (crimson → raspberry/teal, amber →
  gold/green). Duplicate applyAccent removed.
- Consumers: SysMonitor meters switched from hardcoded `--sm-green/amber/
  blue` to `--h-b/c/d` (G = accent, M = h-b, D = h-c, C = h-d), cell color
  passed as inline `--sm-c`; ide-status bar bg = `--h-a` 8% mix; pane
  outer border keeps its accent tint.
- CSS gotcha: `body.pane-resizing .ide-pane { pointer-events: none }`
  (pane-drag mute) also killed splitter drag INSIDE the pane — override
  added: `body.pane-resizing .ide-split { pointer-events: auto }`.
- Frontend built clean. Visual check still pending user restart (structure
  verified in code only).

## Installer rebuilt (2026-10-15 late)
- Full chain: `yarn build` (frontend) → `.venv/Scripts/python.exe -m
  PyInstaller packaging/su1ra.spec --noconfirm --distpath packaging/dist
  --workpath packaging/build` (~51s) → Inno Setup
  `"$LOCALAPPDATA/Programs/Inno Setup 6/ISCC.exe" packaging/su1ra.iss`
  (12.4s) → `packaging/output/Su1ra-setup-x64.exe` (30.3 MB, 22:13 — was
  19.2 MB at v0.3.0; growth = CodeMirror 6 + document-import deps).
- Bundle verified structurally: Analysis-00.toc contains main/store/
  gpumon (gpumon.py picked up from backend/), sysp.txt + frontend/dist
  datas embedded; ISCC "Successful compile". NOT verified end-to-end
  (no silent install/launch test was run).
- SHA256: 1F2A041EB96CDBCA7A8E3DE945E105397D2822DA0EBAC6033BC9930982859411

## Version → 0.3.2 + installer rebuilt with new metadata
- Bumped in all five spots: README title, AGENTS.md header, frontend/package.json,
  header brand-ver in App.jsx (UI shows the version — frontend rebuilt for it),
  su1ra.iss AppVersion. Full chain re-run (yarn → PyInstaller → ISCC, 12.9s).
- Exe metadata: ProductVersion 0.3.2. New SHA256:
  96E01BF03DD4AEDC38AA468B3204E560B1870CEFCDA9873B202A281C59350F1F
  (supersedes the 22:13 build hashed above — that one still said 0.3.1).
- report/AGENTS.md mirror re-synced after the version edits.
- WSL sandbox clarification for the record: the v0.3.1 commit message says
  "sandbox for windows via WSL" but NO WSL code exists in the repo (grep clean
  2026-10-15) — that item is the PARKED task report/report/sandbox-wsl-task.md.
  Windows tool runs today are UNSANDBOXED (bwrap is Linux-only) with only
  runner caps + the loud "sandbox: unavailable" label. Don't repeat the claim
  in release notes.

## WSL sandbox plan expanded in fplan (still unapproved/queued — user: "will add later")
- fplan.md "v2 ideas" one-liner → full plan block: option sweep of record
  (AppContainer reads user files; Windows Sandbox Pro-only + API-less; Hyper-V
  heavier; Job Objects ≠ isolation; Sandboxie driver burden; Docker = WSL
  underneath → WSL2 + bwrap wins), sandbox_backend setting, copy-into-distro-fs
  shape, probe chain, UTF-16 gotcha, scope guard (editor run button stays
  unsandboxed), acceptance summary, machine status. sandbox-wsl-task.md got a
  2026-10-15 probe update (WSL2+Arch present; python3/bwrap not installed yet).

## BUGFIX 2026-10-15 (Windows box): run_python relaunched Su1ra — second app window
- Report: user asked a model to build a script in /build mode; every `run_python`
  call popped a SECOND Su1ra window. The screenshot's "tool output · 10 lines"
  WAS that child's own boot log ([su1ra] window icon set → backend ready → ollama
  ready), then `// timeout — killed after 30s` — a GUI child writes nothing to the
  pipe, so the 30s cap killed it.
- Root cause: `runner.run_python` spawned `sys.executable`. In the PyInstaller
  build (`packaging/su1ra.spec` console=False) that is `su1ra.exe`; the bundle
  ships `python314.dll` but NO python.exe (verified: none under
  packaging/dist/Su1ra). main.py's EDITOR path had already been made
  frozen-aware (commit-era `python_exe()`) — the tool path never got the fix, so
  from-source runs looked fine and only the installed exe misbehaved.
- Fix (backend/runner.py):
  - `python_exe()` now lives in runner and is frozen-aware; honours
    `$SU1RA_PYTHON`, skips candidates named like our own exe (`is_app_exe`) and
    the zero-byte Store alias in `%LOCALAPPDATA%\Microsoft\WindowsApps\`
    (`is_store_alias` — spawning that opens the Microsoft Store). `interpreter_root()`
    follows the SAME interpreter (bwrap ro-bind target was pointing at the app dir).
  - No interpreter found → clean tool result (`error: "no_python"`, install Python
    or set SU1RA_PYTHON) instead of spawning a mystery exe.
  - `child_spawn_kwargs()` → `CREATE_NO_WINDOW` on nt only (passing a non-zero
    creationflags on POSIX raises in subprocess) so console children never flash:
    applied to run_python, /api/run legacy path, `ollama._run_capture` (the
    nvidia-smi/powershell probes ran every sysmon-ish call).
  - main.py `python_exe()` = thin alias to runner's, so the two paths can't drift.
- Verified (this box, source run): compile clean for runner/main/ollama/sandbox/
  gpumon; `run_python('import sys; print(sys.executable)')` → exit 0, real
  .venv python, no window; frozen-simulation (sys.frozen + APP_EXE_NAME=su1ra.exe)
  → picks .venv/PyManager python, exit 0; frozen + Store-alias-only PATH →
  None → `no_python` branch (Store never launched); uvicorn :8123 boot + live
  `POST /api/run` → correct interpreter, exit 0.
- NOT verified: the actual `packaging/dist/Su1ra/su1ra.exe` (needs an Inno
  rebuild — `packaging/build-windows.bat`; the fix is proven under a simulated
  frozen env, not the real exe). Rebuild before shipping.
- Still open (out of scope, deliberately): `desktop.py` has no single-instance
  guard, so any accidental relaunch = two windows + a second :8000 backend. The
  fix removes the trigger; the belt-and-braces lock is a separate decision.
- Unrelated to the parked WSL sandbox task (`sandbox-wsl-task.md`): that is about
  CONTAINMENT of tool runs on Windows; this was about which interpreter runs them.
  Windows tool runs are still unsandboxed + loudly labelled.

## CLOSE-OUT 2026-10-16 (early): the "10-minute hang / files went missing" investigation
- Method: read chat 55 straight from %APPDATA%\su1ra\app.db (messages + stats +
  tool_calls columns). Timeline: 430 ws_mkdir zeta-transform ([folder created])
  → ws_mkdir is ROOT-RELATIVE and does NOT switch projects (workspace.py:168),
  global active_project stayed "cheat" → 434/436 ws_write landed in
  cheat\index.html (7684 B @01:55) + cheat\zeta_transform.py (3385 B @01:58),
  tool results literally read [cheat\...] — model did not react to that.
  zeta-transform\ still EMPTY.

 - 432/438 turns: unclosed <antml:thinking> block, stats column NULL → stream never
  reached the done event, tool_calls NULL → content-fallback parser ignored it
  (only fires when a candidate block STARTS with "{", main.py). The user-visible
  "sat at a loading animation forever" (msg 432 alone ran ~10 min wall-clock)
  was NOT the app hanging — the model was emitting a long rambling thought then
  silently ended the turn ("Now I'll create a clean, well-designed webpage...").
- DECISION (user, 2026-10-16): user re-ran the same sysprompt + same model and
  the model behaved identically → judged a MODEL-side failure (ABQwen3.8-
  4b:latest struggling at 12288 ctx), NOT a software-integrity bug. Therefore
  do NOT add guardrails 1-3 (ws_mkdir autoswitch, done_reason-truncation
  surfacing, promise-without-tool tripwire). They were proposed and
  consciously DECLINED — do not re-propose them next session unless the user
  reopens it. Note on ctx: ~9.6k tokens used of 12288 by msg 438 → raising the
  build-loadout ctx slider (not the code) is the lever for small models.
- Files left in place on purpose: cheat\index.html + cheat\zeta_transform.py
  stay, zeta-transform\ stays empty — user may want them; do not clean up.
- Relevance to the run_python fix: model never reached run_python, so that path
  still only has simulated-frozen verification. The Inno rebuild + real
  build/exe test remains the pending proof.

## IMPLEMENTED 2026-10-16: WSL sandbox backend for Windows run_python
- Follow-up to the handoff (report/report/wsl-sandbox-handoff.md): the code
  plan is now written, wired, and verified on the Windows box (WSL archlinux +
  bwrap + python3 prepared in the handoff session).
- `backend/sandbox.py`: `win_to_wsl()` (drive path → /mnt/c/... direct, no
  wslpath spawn), `_run_wsl()` (UTF-16-safe decode, CREATE_NO_WINDOW
  via runner.child_spawn_kwargs, deferred import to break the runner↔sandbox
  cycle), `wsl_probe()` (cached: 10 min ok / 60s fail; `wsl -l -q` → first
  distro → `command -v bwrap; command -v python3` — never `which`, absent on
  Arch; missing-package reason carries the exact one-time
  `pacman -Syu --needed --noconfirm python bubblewrap` command, the stale-db
  gotcha from the plan), `wsl_wrap(workdir)` (bwrap argv exactly as proven:
  --unshare-all, uid/gid 65534, /usr ro + symlinks, /dev /proc tmpfs /tmp,
  workdir → /work rw via drvfs, --clearenv, PATH /usr/bin, inner
  `/usr/bin/timeout -s KILL 30 python3 -I -u -`).
- `backend/runner.py`: `run_python(code, sandboxed, cwd, backend="auto")`.
  Windows + auto|wsl → probe in a thread → wsl: code piped to python3 stdin
  (NEVER argv), mode="wsl", outer wait_for TIMEOUT+15 so the distro cold start
  isn't billed to the model; inner timeout maps exit 124/137 → timed_out. Probe
  fail → unsandboxed fallback, mode="unavailable" + probe reason. backend off /
  sandboxed False → mode off. Linux path untouched (regression).
- `backend/main.py`: `sandbox_backend` setting (auto|wsl|off, validated) in
  GET/PATCH; run_python dispatch passes backend; tool_result_text prints the
  probe reason (with install command) instead of a generic bwrap hint; boot
  warm probe `start_wsl_warm_probe()` (nt only, skips when off — best-effort
  task like sysmon).
- Frontend: SettingsModal gets «Sandbox backend (Windows): auto/wsl/off»
  select (commitNow path, disabled when the toggle is off) next to the sandbox
  toggle whose label no longer says "Linux only"; `.modal label.sandbox-row
  select` CSS override (the .modal input/select width:100% gotcha again).
  App.jsx boots sandboxBackend from settings, PATCHes it, passes it down.
- VERIFIED (real runs on this box, not simulated): harness with the venv
  python — 14/14: probe ok (archlinux), mode wsl, exit 0, print works,
  cwd /work, uid 65534, root = bin/dev/lib/lib64/proc/sbin/tmp/usr/work
  (no /mnt, no /etc), seed file read through the rw bind, out.txt written by
  the script visible on Windows, net blocked (Errno 101), sys.exit(3) → exit 3,
  `while True: pass` killed at 30.1s by the INNER timeout → timed_out + the
  "killed after 30s" line. Failpaths 7/7 (probe-absent → unavailable + reason,
  backend off / sandboxed False → off, real probe restores wsl). Live server on
  :8124: clean boots with the warm probe firing, settings round-trip
  auto→wsl→422(bogus)→off→auto, PATCH validation. Frontend rebuilt (vite build
  3.85s, pre-existing bundle-size warning only).
- E2E VERIFIED 2026-10-16 (after qwen3.5:0.8b pull): full in-app loop through
  the served UI (backend :8000 + bundled ollama, clicked in a browser):
  /build → new chat #57 (model qwen3.5:0.8b, loadout patched to it) → prompt
  asking for an exact run_python script → model's tool call routed through
  wsl_wrap → tool block rendered: `▸ tool: run_python · 11 lines` / 6 output
  lines — uid 65534, cwd /work, has_mnt False, root ['bin','dev','lib',
  'lib64','proc','sbin','tmp','usr','work'], net blocked [Errno 101] · [exit 0] —
  assistant summary followed. Write-back check: e2e_marker.txt created by the
  script inside bwrap landed at ~/Documents/su1ra_projects/cheat/ (the active
  project = run cwd), marker cleaned after. This closes the prior "NOT verified"
  gap; the only unproven surface left is the frozen exe + a Linux regression
  run.
- Two bugs caught by the harness while implementing: wsl_probe never committed
  its result to _wsl_state (wsl_wrap always saw ok=False → silent unsandboxed
  fallback); win_to_wsl dropped the slash after the drive letter
  (/mnt/cUsers/…). Both fixed + re-verified green.
- NOT verified: the in-app chat tool-block end-to-end (a build-mode message
  where the model calls run_python and the tool block shows sandbox: wsl) —
  ollama starts but this box has no model manifests (blobs orphaned, dirs
  empty), so it needs a hub pull first. The dispatch line is one settings-read
  away from the harness path, but claim nothing until it's clicked through.
  Also unproven: real frozen exe (still needs the Inno rebuild), Linux
  regression run (no Linux box in this session), workdir path with SPACES
  through wsl.exe argv reconstruction (documented limitation).
- Machine state at end of session: temp harness files in
  %TEMP%/su1ra_wsl_harness.py + su1ra_wsl_failpaths.py (rerun anytime —
  nothing in the repo depends on them). app.db sandbox_backend left at default
  auto. git tree has the same uncommitted working-tree changes as before plus
  sandbox/runner/main/App/SettingsModal/index.css edits and doc updates.
