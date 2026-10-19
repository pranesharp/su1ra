# AGENTS.md — Su1ra v0.3.2

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
- `backend/runner.py` — tool-run executor (30s timeout, 2000-line/1MB caps); also owns
  the ONE python resolver `python_exe()` (main.py's editor `python_exe` is a thin
  alias) + `child_spawn_kwargs()` (CREATE_NO_WINDOW on nt) — use both for any child spawn
- `backend/sandbox.py` — sandbox wrappers for tool runs: `wrap()` = bubblewrap
  (Linux, unchanged); `wsl_probe()`/`wsl_wrap()`/`win_to_wsl()` = WSL backend for
  Windows (bwrap inside the WSL distro; model code rides STDIN, never argv)
- `backend/ptyrunner.py` — real PTY for the IDE output terminal
- `backend/store.py` — SQLite; `PROMPT_FILENAME = "sysp.txt"` seeds
  `default_system_prompt` (with `default_system_prompt_bundled` guard so replacing
  sysp.txt re-seeds without wiping chats); `DATA_DIR` frozen-mode aware
- `frontend/src/App.jsx` — command console, mode/loadout state, stream routing
  (streamTargetRef — deltas target the streaming assistant BY ID; onTool attaches
  by role), background model eviction (`unloadInBackground`)
- `frontend/src/components/` — ChatView (markdown+math, user msg copy/edit/redo),
  EditorPane (CodeMirror 6 buffer + xterm output; was IdePane), ArtifactPane (sandboxed iframe; shows file path in workspace
  mode), ModelHub (catalog), OllamaSetup (first-run callout + troubleshooting
  bridge), SettingsModal (autosave), TitleBar (floating window controls — auto-hides
  without js_api), theme.js
- `frontend/src/clip.js` — clipboard helper (navigator.clipboard → textarea fallback)
- `sysp.txt` — BUNDLED artifact-generation system prompt ("The Editorialist-Engineer").
  SACRED: do not rewrite. Code-mode file-workflow rules live in the appended backend
  directive, never in sysp.txt.
- `frontend/dist/` is NOT committed — build before `desktop.py` after a fresh clone

## Modes & loadouts (core V2 concept)

- **casual** vs **build** mode. Per-mode loadout: model, context length, think
  on/off, system prompt (build mode appends the file-workflow directive).
- **Think levels (2026-10-19):** `off|low|med|high|ultra` replaces the on/off toggle.
  Canonical stored values = Ollama's `off/low/medium/high/on` (ultra = on, uncapped; per-chat
  `auto` = null → mode default). Canonicalization: `store.THINK_ALIASES` (med/ultra/max/
  true/false/0/1); `ollama.normalize_think_param` maps off→false, on/ultra→true,
  low/med/medium/high→the level string. Only level-aware templates (gpt-oss family)
  actually budget reasoning — a bool-only template (qwen3 family, `{{ if .Think }}`)
  treats the string as truthy = plain on, so `/think off` is the only real ctx lever
  there. Per-mode defaults: `loadout_casual_think` ('' → off) and NEW
  `loadout_code_think` ('' → med — was hardcoded think-on in build). SettingsModal
  renders a 5-button ladder per mode (`ThinkLadder`); bare `/think` prints the whole
  ladder with ▸ on the current level; `/think <level>` persists per-chat (or the
  CURRENT mode's loadout default when no chat is open). Header + /modes show the
  pretty label (med/ultra). Harness `report/report/repro-think-levels.py`.
- **Prompt-based effort levels (2026-10-19 later — the bool-only lever):** since
  Ollama's own Qwen3.8 renderer implements tiers as system-prompt GUIDANCE
  (model/renderers/qwen35.go "Reasoning effort is set to…"), main.py does the same
  for low/high: `apply_think_effort(sys_prompt, think)` (pure, unit-tested) appends
  `THINK_EFFORT_PROMPTS[level]` at the END of the assembled sys_prompt — BOTH modes
  (casual's guidance line may be the whole system prompt), after the build directive.
  medium = model default and ultra = uncapped → deliberately NO injection (matches
  Ollama); junk think values degrade to no injection. `/api/show` exposes no thinking
  controls, so there's no level-awareness probe — on a real level-aware model the
  renderer's line and ours coexist (harmless redundancy). LIVE-VERIFIED on
  ornith-1.5:9b (bool-only): palindrome task, think:true, same num_predict — without
  guidance 1855 thinking chars, with the low line 116 (−94%), answer still correct.
- **History think-strip (2026-10-19, the ctx fix):** `build_history` (main.py) strips
  the LEADING `<think>…</think>` block from assistant rows before sending —
  `THINK_STRIP_RE` (anchored `^\s*<think`, lazy to `</think>` or `\Z`, so an unclosed
  tail from a dead stream also drops, and a literal `<think>` inside code the model
  wrote mid-answer survives). DB/display/export keep the full text; the tool loop's
  in-memory `working` list keeps the CURRENT request's round reasoning. History scope
  was already per-conversation — the strip stops reasoning accumulating WITHIN a chat.
- **System prompts are per-mode (2026-10-15):** build default = sysp.txt seed
  (`default_system_prompt`); casual default = `default_system_prompt_casual`
  (ships EMPTY — user's choice). Resolution: per-chat override → else mode
  default; empty = no system role sent. SettingsModal is mode-aware (mode prop)
  and saves with `systemPromptScope` 'default'|'chat' — default edits never
  re-stamp the open chat. NEVER stamp a global default into a new conversation's
  `system_prompt` at create time (that was the leak; one-time normalization
  `perchat_sysp_norm` cleared old stamps, customs survive).
- **Mode is persisted per conversation** (`conversations.code_mode`, 0/1):
  createConversation passes it (birth mode). **Mode switch = new chat**:
  `/build` (both toggle directions) and `/casual` call `startModeChat` — a
  fresh chat on the new desk; the chat being left keeps its mode/history
  (an EMPTY chat with zero messages is retagged + reused instead). **Opening
  a chat follows the chat** — `selectConversation` flips codeArmed + picker/
  new-chat defaults to its mode's loadout (light switch: no settings rewrite,
  no forced IDE). `/chats` renders TWO columns (BUILD left, CASUAL right)
  from `code_mode`; ordinals stay global for `/chats <n|id>`.
- **Naming (2026-10-13):** the mode the user sees is **build** (`/build`) — renamed
  from "code" because it covers decks/docs/sheets/SVGs, not just code. INTERNAL
  identifiers keep the old names on purpose (no DB/API migration): API field
  `code_mode`, settings keys `loadout_code_model`/`loadout_code_ctx`, JS
  `codeArmed`/`codeMode`/`leaveCodeMode`. `/code` still works as a hidden alias
  (handled in the same App.jsx branch, not listed in COMMANDS).
- `/modes` prints mode + effective model + ctx/think/tools/sysprompt/engine.
  Header shows `· casual/build · model: ... · think: ...`.
- Startup boots to a fresh **casual** desk (no chat auto-opened; history in /chats).
- Switching modes unloads the other loadout's resident model via
  `POST /api/models/unload` (keep_alive: 0) — **fire-and-forget in background**
  (`unloadInBackground`), only when models differ, never on /newchat/boot.
  Optimistic UI first (mode switch must never await eviction).
- `/casual` exits build mode (shared `leaveCodeMode` path).

## /build mode + workspace

- Tools offered ONLY when `body.tools and body.code_mode` — **strict server-side
  gating**; the old ```python auto-arm in casual was removed.
- **Off-template tool-call healing (2026-10-17):** small models sometimes break their own
  tool-call template and leak raw tokens as content (`<|tool_call|>call:read_document[doc:1]
  <|tool_response>`) — Ollama parses no tool_calls, the old content-fallback only accepted
  bare JSON, so the turn ended as garbage and the model waited forever for a tool response
  that never came. `detect_content_tool_call` now strips the leaked tokens/think markers and
  heals `call:NAME[k:v]` / `NAME({json})` / `NAME(k=v)` shapes (NAME must be a real tool;
  last match wins) so the tool runs and the loop continues.
- **request_resources (2026-10-17, 7th tool):** build-mode RAG loop — when the model
  needs authoritative ground truth (exact API signatures/types/flags, format specs,
  protocol details) it calls `request_resources` (items: topic/why/search_hint;
  normalize-don't-reject, clamp 10), the backend records a pending request, and the tool
  result teaches STOP-AND-WAIT. The user answers via the **resource cart** (see /web
  section); pages arrive as `kind="document"` attachments (`meta.source="context_resource"`)
  on a synthetic user message, so the EXISTING [doc N] labeling + `read_document` +
  `attach_to_message` all apply unchanged. `GET /api/context/resource-request?conversation_id=`
  = poll target; `POST /api/context/cart/send` = deliver (items[] raw|summarize + optional
  base64 image items; summarize = one-shot non-streaming `{ollama}/api/chat` on the
  conversation's model, falls back to raw on ANY failure; per-item errors never fail the
  batch; raw cap 150k; empty items = Skip). Directive gains a REFERENCE DISCIPLINE
  paragraph (build mode only; sysp.txt untouched). Harness:
  `report/report/repro-resource-cart.py` (30 checks, temp APPDATA).
- **Attachment numbering is per-CONVERSATION (2026-10-17 fix):** `attach_to_message`
  seeds per-kind counters from `MAX(idx)` of linked rows (`store.max_attachment_idx`) and
  the chat handler's label math uses the same base — a second doc/image batch in one chat
  CONTINUES at [doc N+1] (per-message restart used to collide with read_document's
  conversation-wide numbering). `get_attachments_for_conversation` orders linked rows
  (idx>0) first, pending (idx=0) last, so read_document's doc N == the labeled [doc N].
- 6 workspace tools registered (ws_ls/ws_read/ws_write/ws_edit/ws_mkdir/ws_cd);
  `run_python` cwd = active project dir.
- **Project rule (2026-10-13):** the model starts every new project in a NEW
  folder via `ws_cd <name>` (mkdir-if-missing + switch in one call) — it never
  writes into the workspace root or silently reuses the active project.
  `active_project` is a global setting, so a model-driven ws_cd switches it
  for the whole app; the frontend header syncs from the ws_cd tool event.
- `build_pptx` tool (added 2026-10-13, `backend/pptx_builder.py`): model sends a
  JSON outline (filename/theme/slides), the BACKEND renders the .pptx — the model
  never touches coordinates. Writes `<stem>.pptx` + `<stem>.preview.html` (a
  self-contained slide player) into the project dir; same filename = regenerate
  in place (that IS the revision loop). The tool event reports the player html
  as `path`, so the frontend artifact bridge opens it in the preview pane.
  One theme/layout dict feeds BOTH the pptx and the player (preview px = slide
  pt, 960x540 stage = 13.333x7.5in at 72px/in) — keep them in sync there.
  Runs in-process (like ws_* tools), not through run_python — no sandbox
  involved. Outline errors raise `OutlineError` → tool text tells the model
  how to fix. `run_python` remains the escape hatch for exotic pptx needs.
- Auto-context injection: live project listing (60 cap) as a TRAILING `[context
  note]` message after the newest outgoing message every build turn (was: appended
  to sys_prompt — which sits at the TOP of the payload, so every ws_write's size
  change busted llama-server's KV prefix slot and forced a full history re-prefill
  at the iGPU's ~214 tok/s: measured 14.8s TTFT vs 0.61s cache-hit on the same
  3032-token prompt, 2026-10-19). The system prompt is now byte-stable per mode —
  only a stable `listing_note` pointer remains in the directive; the no-project
  /mkdir+/cd guidance still injects into sys_prompt (rare, once per project start).
  Tail message is request-only (never the DB); the tool loop re-copies `history`
  per round so the note rides at a prefix-stable position. Best-effort, never
  breaks the turn.
- `/mkdir <name>` + `/cd <name>` commands; `workspace_root` + `active_project` in
  settings GET/PATCH with validation; `/api/workspace/mkdir|read|ls`.
- **New chats start at the workspace root (2026-10-17):** `newChat()`/`startModeChat`
  (both branches) reset `active_project` to '' first — a fresh chat never begins inside
  the last project; the model re-derives /mkdir+/cd guidance. Opening an OLD chat does
  NOT touch the project.
- **/logsave [md|json|txt] (2026-10-17):** `POST /api/conversations/{id}/export` writes
  `<workspace_root>/su1ra-logs/<title>-<stamp>.<ext>` — md: `## USER/ASSISTANT/TOOL #n`
  + thinking as a highlighted `> **◈ thinking**` quote; json: per-message `thinking`
  field; txt: ~~~~ thinking/answer ~~~~ sections. User-facing command; the model never
  calls it.
- Model `.html` writes/edits in workspace mode auto-open/refresh the artifact
  preview with a `// preview:` line.
- Out-of-bounds ops = hard deny + the model explains in text. Approval popup is a
  parked v2 idea.

## /web browser pane (right split pane)

- `/web <url|query>` opens a lightweight browser in the right pane (ArtifactPane
  browser mode): URL bar, back/fwd/refresh, engine picker (default Bing), badge
  (`✓ html` / `✗ js` / `✗ blocked`), `[ open externally ]`, `[ summarize page ]`.
  No search API/scraping — all of that was deleted.
- **Link clicks → pane (GTK + Windows):** result links are `target="_blank"`.
  GTK: pywebview's own `decide-policy` handler (`gtk.py` `on_navigation`) runs
  first and would `load_url` the main webview (replacing the app). `desktop.py`
  `_install_new_window_handler` DISCONNECTS it (`disconnect_by_func`) and
  installs one wrapper: `_blank` → `window.__su1raOpenInPane(url)` +
  `decision.ignore()`; everything else delegated to pywebview's `on_navigation`.
  Install-once guard (`wv._su1ra_pane_nav`) — `events.loaded` fires for splash
  AND app. **Windows (2026-10-16):** the same bug persisted on the WinForms/
  EdgeChromium backend (user hit it on the Windows boot) — pywebview's
  `EdgeChrome.on_new_window_request` calls `load_url` (sets WebView2 Source →
  replaces app). Added `_install_new_window_handler_win()`: on `nt` the
  dispatcher routes to it; it finds `winforms.BrowserView.instances` →
  `EdgeChrome`, marshals onto the UI thread via `wv.Invoke(Action(...))` and
  polls up to ~4s until the native `CoreWebView2` is ready (it's only reachable
  on the UI thread, but `events.loaded` callbacks run on worker threads), then
  detaches `NewWindowRequested` and attaches a handler that
  `set_Handled(True)` + `ExecuteScriptAsync("…__su1raOpenInPane(…)")`.
  Iframe sandbox MUST keep `allow-popups` (it carries the URL; without it WebKit
  sends about:blank).
- **Bing redirects:** results are `bing.com/ck/a?...&u=a1<base64url>`;
  `unwrapRedirect()` (App.jsx) decodes them in `browserNavigate` and
  `__su1raOpenInPane`, otherwise the backend fetches a JS stub → `✗ js`.
- **Summarize:** `/api/page/summarize` returns page text (~12k cap);
  `conversation_id` is optional (null on a fresh boot with no chat — was a 422).
  Frontend sends it via normal `send()` (creates chat + loads model). ChatView
  renders these messages as `// summarize page: <title>` (`PAGE_SUMMARY_RE`,
  display-only; full text stored/sent; no `[ edit ]`).
  **Wrong-`?`/no-summarize on some pages (fixed 2026-10-16):** the badge +
  summarize button are driven by the backend's own `page_info`/`fetch_page_text`
  httpx probes. When a page bot-blocks the backend's egress IP (e.g. Wikipedia
  returns 403 to a Cloudflare-WARP-routed Python egress, while the WebView2
  iframe renders it fine on a different path) the probe yields `kind=binary`/
  `unknown`, which used to fall through to a `?` badge + "checking page..." with
  NO summarize button. Now: such pages show `✗ probe` + a "couldn't probe from
  the backend" note and STILL offer `[ summarize page ]` (best-effort — 502s
  with a clear message if genuinely unreachable). The iframe (real browser
  stack) keeps powering the visible page regardless.
- Known limits: in-iframe navigation isn't tracked (summarize uses the last
  pane-level URL); Google/Brave/DDG refuse framing.
- **Resource cart (2026-10-17):** `[ add to cart ]` beside `[ summarize page ]` stages the
  page (dedupe by URL; per-row raw/summarize select; cart persists in localStorage
  `su1ra_cart`). When the model's `request_resources` ask is pending (1.5s poll in
  App.jsx), a **composer resource strip** lists the topics with `[ find in /web ]` buttons
  (opens the pane pre-searched, same as `/web <query>`), `[ send cart (n) ]` / `[ skip ]`
  at the input — the loop is one click each without touching pane chrome. Send =
  `POST /api/context/cart/send` → pages stored as [doc N] documents → synthetic
  "Resources provided per your request…" user message. Skip = fulfill + "User declined…".
  `snap to cart` screenshots the pane INTO the cart (kind:image; capturePage(dest)).
- **Pane divider drag:** `onPointerDown` (NOT onMouseDown — pointer capture needs a
  pointerId), `body.pane-resizing` disables iframe/pane pointer events during drag,
  width clamped to `[280, min(1200, innerWidth - 360)]`.

## Settings (autosave — no Save/Cancel)

- Text inputs debounced 500ms; dropdowns/swatches/toggles save instantly
  (`commitNow`); flush-on-unmount; `/settings` gated on boot completion.
- Defaults (`default_system_prompt` / `default_temperature` /
  `default_context_length`) persist in the settings store; new conversations inherit
  them. Do NOT create conversations with `{model}` only — that was the original bug.
- Engine selector: Auto/CPU/GPU + TWO independent checkboxes (Vulkan, integrated
  GPU) with live detection (`GET /api/gpu`:
  nvidia-smi, vulkan loader, adapter names), env preview, `[ restart server ]`
  (`POST /api/ollama/restart` refuses foreign servers). `ensure_running` applies
  `engine_env()` to spawned servers.
  **Hard switches (2026-10-19):** in auto+gpu modes `engine_env()` emits
  `OLLAMA_VULKAN` and `OLLAMA_IGPU_ENABLE` as explicit 1/0 per checkbox
  (`engine_vulkan` / `engine_igpu` settings; cpu mode still hides every
  backend). Rationale — stock 0.40.x defaults cut both ways: Vulkan runner libs
  load by DEFAULT (unchecked used to silently stay on) while Vulkan iGPUs are
  DENIED by default (`discover.integratedGPUAllowedByDefault`: CUDA +
  whitelisted ROCm GFX only), so the old gpu-mode unconditional
  `OLLAMA_IGPU_ENABLE=1` could let an iGPU steal the model from a discrete
  card (RX 580 gfx803 is invisible to ROCm — Vulkan is its only offload path;
  the bundled engine ships `lib/ollama/vulkan/ggml-vulkan.dll`). FX: friend =
  Vulkan ✓ + iGPU ✗; iGPU-only box (Arrow Lake) = both ✓. Upgraders on gpu
  mode with a previously-implicit iGPU offload must tick iGPU once — the env
  preview shows exactly what a restart will apply.
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
- **Never spawn `sys.executable` as a child (2026-10-15):** frozen, it IS
  `su1ra.exe` (the bundle ships `python3xx.dll`, no `python.exe`), so the
  `run_python` tool RELAUNCHED THE APP — a second Su1ra window whose boot log
  came back as "tool output", then `// timeout — killed after 30s`. Use
  `runner.python_exe()` everywhere (main.py's editor copy is now an alias); it
  also skips the zero-byte Store alias in `…\WindowsApps\` (would open the
  Store) and honours `$SU1RA_PYTHON`; no interpreter → clean tool result, never
  a blind spawn. `runner.child_spawn_kwargs()` adds `CREATE_NO_WINDOW` (nt only
  — POSIX raises on a non-zero creationflags) so console children do not flash
  terminals; applied to runner, `/api/run` legacy path, `ollama._run_capture`.
  Still open: `desktop.py` has no single-instance guard, so a relaunch = two
  windows + a second :8000 backend.
- **WSL sandbox backend (2026-10-16):** Windows tool runs route through
  `wsl.exe -d <distro> -u root --cd / -e bwrap …` when `sandbox_backend` ∈
  auto|wsl (default auto); off, or no WSL/bwrap/python3 → unsandboxed with a
  loud label carrying the exact one-time install command. Distro-prep gotcha:
  plain `pacman -S` fails on a stale db — use
  `pacman -Syu --needed --noconfirm python bubblewrap` via `-u root`
  (no password). Probe with `command -v`, never `which` (absent on Arch).
  Model code is piped to `python3 -I <stdin>` — NEVER part of the argv
  (wsl.exe quoting); workdir binds rw at /work (`win_to_wsl` → drvfs), no
  /mnt (Windows drives invisible), uid 65534, no network. Warm probe at boot
  (off the request path) so the distro cold start isn't counted against the
  cap: inner timeout stays 30s (inside bwrap), outer wait_for loosened +15s.
  `sandbox:` field in tool results now says wsl / on / off / unavailable.
  Editor runs stay unsandboxed; Linux bwrap path untouched.
- **Sysmon (2026-10-15):** `/api/sysmon` + background sampler (2s, pure stdlib
  — no psutil) in main.py; `SysMonitor.jsx` renders 2x2 SEGMENTED meters (10 fixed-px
  blocks between [ ], ghost blocks when idle; G/M/D/C, colors from the
  accent-derived hue family (G = accent, M = --h-b, D = --h-c, C = --h-d —
  NOT hardcoded green/amber/blue anymore; inline `--sm-c` per cell),
  no numbers, tooltip only; NEVER %-width fills inside the shrink-to-fit track —
  that rendered every bar at 0px). States: live / unavailable (flat line) /
  offline (cluster dimmed) fixed bottom-left in the
  composer foot; hidden < 1180px. GPUs: `backend/gpumon.py` (in spec
  hiddenimports) → `gpus` list, iGPU FIRST. Windows = DXGI EnumAdapters1
  (ctypes vtable: factory slot 12, GetDesc1 slot 10; skip software adapter)
  + PDH `\GPU Engine(*)\Utilization Percentage` (sum per engine, adapter =
  busiest engine — Task Manager rule; any vendor incl. Intel iGPU/Vulkan) +
  `GPU Adapter Memory` for the tooltip. Linux = AMD sysfs + nvidia-smi.
  Layout: col1 = M then G_{n-1}..G₁, G₀ at the BOTTOM (extra GPUs stack
  upward on G₀); col2 = D over C; columns bottom-aligned. shutil.disk_usage has NO `.percent` — compute used/total.
- pywebview **frameless chrome is PARKED**: flaky WinForms init race in pywebview
  6.2.1 (app hang, black window, intermittent — bisected clean at every step).
  Do not retry without a newer pywebview or different shell. Mitigations that stay:
  splash self-navigates via JS poller (never `load_url`/`evaluate_js` from worker
  threads), `PostMessage` for the icon.
- Theme flash fix: `serve_index()` stamps `window.__SU1RA_THEME__` into served
  index.html; `theme.js` seeds from it — first paint uses saved accent/brightness.
- Data: `%APPDATA%\su1ra\app.db` (Linux: `~/.local/share/su1ra/`).

## CSS gotchas (hit before)

- **`setAccent` guard (2026-10-17, black-screen class of bug):** the component
  `saveSettings` must NEVER `setAccent(newAccent)` unconditionally — a caller without
  `accent:` (e.g. the /build project reset) undefines the theme, the `[accent]` effect
  runs `applyAccent(undefined)` → `hexToRgb(undefined).slice` throws → React unmounts →
  near-black empty window. Guarded + `applyAccent` falls back to `DEFAULT_ACCENT`.
  Note: a DOWN ollama masks it (`getStatus()` throws first). Suspect this class when the
  app shows the bare black body.

- `.modal input { width: 100% }` out-specifies single-class rules — any new input
  inside the modal needs a `.modal`-scoped override or it stretches and crushes
  flex siblings (broke the ctx slider once; commit 0d65371).
- `.gitattributes` marks `yarn.lock` linguist-generated.
- `body.pane-resizing .ide-pane { pointer-events: none }` (pane-drag mute)
  reaches INSIDE the pane and kills the `.ide-split` drag row — keep the
  override `body.pane-resizing .ide-split { pointer-events: auto }`.

## Command surface

/help · /models (+ `pull <name>`, `get [query]`) · /chats · /delchat (<n|id>, `all`
wipes everything) · /clear (current chat messages only, chat + settings kept) ·
/newchat · /build (toggle; `<msg>` one-shot; /code hidden alias) · /casual · /modes · /mkdir · /cd ·
/think (bare = the ladder menu; `off|low|med|high|ultra|auto`, this chat, persisted) ·
/rename <title> (names the current chat; freezes it against auto-title) ·
/settings · /stats · /logsave [md|json|txt] · /editor (/ide alias) · /eject · /connect · /web <url|query>

## Editor pane (2026-10-15 — renamed from /ide, general-purpose)

- **v2 same day:** files live in `~/Documents/.scratch` (`editor_root()`; the
  legacy APPDATA scratch is copied over once). Subpaths are first-class:
  `_editor_rel_path` validates per segment (no `..`), run cwd = the file's
  PARENT dir (sibling imports), save auto-creates parents. `/api/editor/open`
  reads a file back into the buffer (400k cap; `rel` is `as_posix()`), 
  `/api/editor/tree` = recursive listing (depth 5, 800 entries), 
  `/api/editor/mkdir` makes folders or empty files. **`/api/editor/delete`
  (2026-10-17) = user-side file/dir delete (rmtree for dirs; traversal + root
  refused)** — the model's workspace tools still have NO delete, by design.
  Frontend: per-row `−` (two-click confirm − -> `sure?`; native confirm() is
  unreliable in webviews); deleting the open file resets the buffer.
  Filled `.btn-solid` action buttons (+ .ghost/.done variants) on the NEW
  surfaces (explorer head, browser foot, resource strip, cart) — pane chrome
  keeps the [ bracket ] style. CodeMirror 6
  (basicSetup + per-ext lang; theme Compartment follows data-mode; Mod-s
  keymap + window ctrl+s), explorer sidebar (open / +file / +dir / row
  delete), dirty = `code !== snapshot` → `· unsaved` marker. run() reads `codeRef`.
- `/editor` toggles the right pane (hidden `/ide` alias kept). Settings keys
  STAY `ide_open`/`ide_width` (DB compat — same precedent as `code_mode`).
  Component: `EditorPane.jsx`; state editorOpen/editorWidth/editorCode/editorName.
- The buffer belongs to a FILENAME (header input, default scratch.py). Run
  SAVES the buffer to `<DATA_DIR>/scratch/<filename>` and executes the FILE by
  extension: .py → python (frozen-aware `python_exe()` — sys.executable in the
  bundled exe is su1ra.exe, NOT python; fall back PATH python/py), .js/.mjs/.cjs
  → node, .sh/.bash → bash/sh, .ps1 → powershell -File, .bat/.cmd → cmd /c,
  .rb/.pl/.lua. Missing interpreter / non-runnable ext (md, txt, json…) →
  clean 422 (frontend disables run: "save only"). Filename validated by
  `_FILENAME_RE` (basename, no traversal). `POST /api/editor/file` saves
  without running. Legacy (non-PTY/Windows) path spawns argv with 30s cap;
  Linux PtySession now takes (argv, cwd, env) — generic exec, was python -c.
  attachEditorRun labels `// attached: editor run — <file> (exit n)` with
  ext-matched fence.
- **btop panels (2026-10-15):** every pane section is a `.panel.h-a/b/c`
  box (scratch explorer=h-b, code editor=h-a, output=h-c) with punched
  `.panel-title` + `Corners()` glyphs (┌┐└┘ on the border line). Panel hue
  = one custom prop `--ph` / `--ph-line`; the four hues come from
  `theme.js` `deriveHueFamily(accent)` (analogous rotations +45/−50/+105,
  sat damped) set by `applyAccent()` as `--h-a/b/c/d` — recolors the whole
  system on every accent pick.

## History semantics

- **Chat naming (2026-10-19):** every chat gets a title three ways, priority =
  manual > AI > derived. (1) First user message stamps `derive_title(content)`
  (whitespace-collapsed single line, 48 cap — was raw `content[:60]`, which is
  where every chat became "hi"). (2) After the FIRST exchange completes, the
  frontend fire-and-forgets `POST /api/conversations/{id}/auto-title`
  (`generate_chat_title` = one-shot non-streaming /api/chat on the chat's own
  model, think:false, num_predict 32, 20s timeout; `_clean_llm_title` strips
  think wrappers/"Title:" labels/quotes and takes the first line; ANY failure
  → falls back to the derived title; never raises). Response patches
  conversations state — header + /chats update live. Trigger = `firstExchange`
  (no user/assistant messages in state at send time); skipped on abort; old
  chats already titled "hi" are NOT retro-fixed (no messages-empty moment —
  /rename them). (3) `/rename <title>` PATCHes the title and sets
  `conversations.titled_manually = 1` (migration, ALTER + DEFAULT 0) — the
  auto-titler and re-derive NEVER touch a manual title. `/clear` wipes title
  AND the flag (blank slate, auto-title fires again on the next exchange).
  Harness `report/report/repro-chat-naming.py` (LLM monkeypatched).

- User messages render copy / edit / redo; edit + redo truncate via
  `DELETE /api/messages/{id}/following` then resend. Chat stream emits real
  `user_id` (first event) and `assistant_id` (done event) — UI must target DB ids.
- Artifact HTML block extraction is tolerant (unclosed fence, case-insensitive);
  open/download buttons render only when extraction succeeds (commit 5100c13).

## Models seen in the wild

- Linux daily driver: `ornith-1.5:9b` (ollama library; qwen35 base, 9B, 262k ctx,
  Q4_K_M; tools/thinking/vision — native tool calls work well). `deepseek-r1:1.5b`
  never emits tool_calls (content-fallback path). qwen2.5-coder:7b was removed.
- **Level-aware think (verified 2026-10-19 against ollama source + live /api/show):**
  on the bundled 0.40.1 engine only the gpt-oss family (harmony) maps Think to
  low/medium/high — every other installed model is bool-only, so `/think off` is the
  real ctx lever. Newer engines (renderer layer) add: Qwen3.8 (false/low/medium/xhigh —
  unsupported strings fall to DEFAULT xhigh, our "high" included), glimmer
  (false/low/medium/high/max), nemotron3nano v3.5 (+"medium"). See session-log.
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
  v0.3.1 release + SHA256 checksums + terminal-styled landing page wired to
  `releases/latest/download/Su1ra-setup-x64.exe`.

## Parked / someday (from report/report/fplan.md)

- In-chat allow/disallow popup for out-of-bounds ops (pausable agentic loop)
- /mkdir scaffolding contents · history-stripping of superseded artifacts ·
  preview scroll/slide-state preservation · frameless chrome revisit ·
  real .pptx path (python-pptx) — (WSL execution backend toggle: DONE — shipped
  2026-10-16, see the "WSL sandbox backend" bullet under Platform notes)

## Arch/Linux fresh-machine setup (learned 2026-10-13)

- System needs: gtk3, webkit2gtk-4.1, python-gobject (pacman). The venv hides system
  site-packages by default, so `import gi` fails inside .venv even with python-gobject
  installed — bridge it: echo "/usr/lib/python3.14/site-packages" >
  .venv/lib/python3.14/site-packages/system-gi.pth (or create the venv with
  --system-site-packages). Verify: `gi.require_version('WebKit2','4.1')` imports.
- Desktop boot sequence in the log: backend ready → ollama detected → ollama ready.
- Engine install via in-app flow proven on this machine: real 1.44 GB stream, extract,
  spawn from <app>/ollama/bin/ollama; models in ~/.ollama survive engine removal.

## ACTIVE TASK (2026-10-16): WSL sandbox for Windows run_python

- IMPLEMENTED + VERIFIED 2026-10-16 (Windows box): `sandbox.py` gains
  `wsl_probe()` (cached detect; `command -v`, never `which`) +
  `wsl_wrap()`/`win_to_wsl()`; `runner.run_python` gains `backend=` (auto|wsl|off)
  with a stdin-feeding WSL branch (code never in argv) and a +15s outer cap;
  `main.py` gains the `sandbox_backend` setting + boot warm probe; SettingsModal
  has a backend select. Real-WSL harness: 14/14 (print, cwd /work, uid 65534,
  no /mnt, workdir rw bind, net blocked, exit-code propagation, 30s cap via
  inner `timeout -s KILL`) + 7/7 failpaths + live settings round-trip + clean
  boots. E2E through the served UI with qwen3.5:0.8b: model's run_python call
  rendered uid 65534 / cwd /work / no /mnt / net blocked / [exit 0] in the chat
  tool block, and a file written inside bwrap landed in the active project on
  Windows. Unproven: frozen exe + Linux regression only — see
  report/report/session-log.md close-out. This supersedes the "parked" note on
  the WSL task below.

## NEXT SESSION STARTS HERE (2026-10-16 late handoff — web batch IMPLEMENTED, awaiting user click-through)

- **Read this FIRST for the /web work: `report/report/web-features-next.md`** (now
  marked RESOLVED). All three open items are implemented in the working tree +
  rebuilt dist (uncommitted until the user clicks through):
  - **A. `[ capture ]` FIXED**: `desktop.py.capture_pane` now uses Pillow
    `ImageGrab.grab()` + `GetClientRect`/`ClientToScreen` + virtual-screen scale
    `f` on a WORKER thread (PrintWindow deleted — it yields a black bitmap). Pane
    rect crop when the frontend ({x,y,w,h}; dpr ignored) is passed; else full
    client area. Mechanics verified against a real window on the live desktop.
  - **B. Casual "thinking" leak ROOT-CAUSED**: the casual loadout model
    `abminicpm52b:latest` is a GGUF-only MiniCPM5-2b-abliterated import with a
    bare `{{ .Prompt }}` template — **Ollama ignores `think:false` for it**
    (verified live through `/api/chat`: identical ' thinking' preamble with
    false/omitted/system-directive; reasoning arrives in the CONTENT channel,
    not the `thinking` field). The frontend send path was NOT the bug (new
    SU1RA_DEBUG log at main.py:1596 proves `body='off'` reaches the backend).
    splitThinking fix (2026-10-17, supersedes the 6e955e6 strictClose rule —
    see session-log): markers are the backend's own `<think>`/`</think>` wrappers
    (`6e955e6` searched `' thinking'`/`' response'`, which never occur in real
    content, so NOTHING ever collapsed and reasoning rendered raw). Unclosed
    `<think>` tail collapses while streaming and, on the final render, splits at
    its LAST `\n\n` — the answer stays visible as content; no blank line →
    collapse all. Harness `report/report/repro-split-thinking.mjs` (19 cases) +
    shipped-bundle live e2e PASS. **No request-level lever stops MiniCPM thinking
    — but it is no longer on this box (models now: AbGem4-e2b + Qwen3.8-9b);
    re-check the casual loadout in /settings.**
  - **C. adblock** — backend re-verified via curl (blocklist injected into head);
    `ab: on` click-through still pending.
- Also DONE + user-confirmed this session: **EdgeChromium link-click fix** —
  `desktop.py._install_new_window_handler_win()` (pane clicks no longer replace the
  whole app on Windows; GTK path untouched). And the **WSL sandbox is COMPLETED + 
  shipped** (committed `3300ce2`/`e5f0ed0`) — see `report/report/wsl-sandbox-done.md`.
- Commit discipline (updated): the broken PrintWindow capture is gone — nothing
  broken holds the commit. USER CONFIRMATION STILL REQUIRED by clicking through
  the desktop app: [ capture ] → screenshot in chat, casual /web summarize with
  think off, `ab: on` on a fetchable page. Then commit the batch.
- Machine state: venv (.venv), UI rebuilt (vite build ok), bundled ollama boots
  clean (0.40.1 — `/api/show` is POST in this version). Models actually on the
  box NOW: ONLY `abminicpm52b:latest` (casual loadout) and `Qwen3.8-9b:latest`
  (build loadout) — the qwen3.5/gemma/deepseek list below is STALE, those models
  are gone. Backend httpx egress is Cloudflare-WARP-routed → Wikipedia 403s the
  backend but the WebView2 iframe renders fine (probe-vs-render divergence).
- Queued next (user's list, not started): v0.3.2 GitHub release + SHA256 checksums +
  terminal-styled landing page; npm-vs-yarn decision.
- Browser pane bug (link clicks replacing the app) RESOLVED late 2026-10-13, plus
  follow-ups (Bing unwrap, compact summarize line, fresh-boot summarize 422, divider
  drag). Fresh-boot summarize + divider drag await user confirmation. See the
  "/web browser pane" section above and the end of report/report/session-log.md.
- User communicates goals + discusses before builds; verify UI claims by clicking
  through the live app (backend serves built UI on :8000 — most reliable surface).
