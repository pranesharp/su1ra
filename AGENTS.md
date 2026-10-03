# AGENTS.md — Su1ra

Local-first, terminal-styled desktop chat app for Ollama models. Everything runs
on the user's machine: React+Vite frontend, FastAPI backend (:8000), pywebview
desktop shell (`desktop.py`), SQLite at `~/.local/share/su1ra/`.

This file carries project context across machines/sessions. Keep it current.

## Layout

- `backend/main.py` — all routes; chat streaming (NDJSON), tool loop, `/api/run` (IDE), settings
- `backend/ollama.py` — Ollama client; model caps via `/api/show` (tools/thinking detection)
- `backend/runner.py` — tool-run executor (subprocess, 30s timeout, 2000-line/1MB caps)
- `backend/sandbox.py` — bubblewrap wrapper for tool runs (Linux only)
- `backend/ptyrunner.py` — real PTY for the IDE output terminal
- `backend/store.py` — SQLite store; `DATA_DIR` handles frozen (PyInstaller) mode
- `frontend/src/App.jsx` — command console (`/help`, `/models`, `/code`, `/ide`, …), state
- `frontend/src/components/` — ChatView (markdown+math), IdePane (xterm.js), ArtifactPane (iframe), SettingsModal
- `frontend/dist/` is NOT committed — run `yarn build` before `desktop.py` after a fresh clone

## Design decisions (do not undo without good reason)

- **Tools are gated by `/code`** (commit 2fe9a05): tool definitions are only sent and
  the content-fallback detector only fires when armed — bare `/code` toggles per-chat,
  `/code <msg>` is one-shot, pasted ```python auto-arms. Models over-trigger otherwise.
- **Tool runs are sandboxed** with bwrap when available (no network, home hidden under
  a tmpfs, read-only root, only `~/.local/share/su1ra/scratch` writable). venv is
  re-bound read-only so the interpreter exists. Missing bwrap → runs unsandboxed but
  labels it in the tool block. Settings toggle: `sandbox_tools` (default on).
- **IDE runs are never sandboxed** — user-run code is trusted (terminal trust model).
- **`show_stats` and `ide_open` are session-scoped** — reset to off at every app start.
  Real preferences (accent, ide_width, ollama_url, sandbox_tools) persist.
- **Linux distribution is git-pull only**; the tarball was removed from git history
  (GitHub 100MB limit). Windows installer is the only packaged artifact.
- **Installer installs the server-only Ollama engine** — Su1ra is the GUI; no tray app.
- Math rendering via remark-math/katex; thinking blocks stay raw text on purpose.
- Artifacts: single-file HTML only → sandboxed iframe preview (allow-scripts), no
  version slider, no multi-file projects in v1.

## Model notes

- Tested with `ornith-1.5:9b` (official ollama library model — qwen35 base, 9B, 262k ctx,
  Q4_K_M; capabilities: tools, thinking, vision; native tool calls work well) and
  `deepseek-r1:1.5b` (never emits tool_calls; needs the content-fallback path).
- qwen2.5-coder:7b was removed by the user; don't assume it's installed.

## Immediate TODO — Windows boot

1. Clone repo; `python -m venv .venv && .venv\Scripts\pip install -r backend\requirements.txt pyinstaller`
2. `cd frontend && yarn && yarn build`
3. Install Inno Setup 6, run `packaging\build-windows.bat` → `Su1ra-setup-x64.exe`
   (first run WILL surface PyInstaller/hidden-import issues; debug iteratively)
4. Check WebView2 presence; add the runtime install line to `su1ra.iss` if missing
5. Verify installer on a clean-ish machine; e2e: chat, tool run (expect loud
   "sandbox unavailable" label — bwrap is Linux-only), IDE PTY fallback, model download

## Later (roughly prioritized)

- ConPTY for Windows terminal (pywin32) — current fallback is the old pipe renderer
- Job Objects for Windows tool-run limits
- GitHub Releases page + checksums (SHA256) + landing page (terminal-styled,
  links to `releases/latest/download/Su1ra-setup-x64.exe`)
- Engine-agnostic backend (OpenAI-compatible adapter; custom server URL)
- Chat export, RAG via Ollama embeddings, image input, streaming tool rounds

## Model downloads (commit pending)

- `POST /api/models/pull` streams Ollama's pull progress as NDJSON; client disconnect or
  `POST /api/models/pull/cancel` aborts the pull server-side (`backend/puller.py`).
- Two UIs: console `/models pull <name>` (live-updating system line, bare `/models pull`
  cancels a running pull) and a Settings-modal section (chips + progress bar + cancel).
- No in-app catalog browsing (undocumented API) — typed names + curated chips; `/models get`
  opens the ollama.com library for discovery.
