# Task: Document import (Tier 2 of file-import feature)

Status: BUILT (2026-10-13) — backend + frontend done, builds clean, verified
live by the user (documents import via picker and drag & drop).
Tier 3 (video) is parked — see `fplan.md`.

## Scope

Attach documents to a chat message so the model can read them. Covers the
formats a UG student actually meets: PDF, Word, PowerPoint, Excel, CSV, and
**all plain-text/code files**.

## Key design decision: code files need no parser

A `.py`/`.js`/`.c` file *is* text — there is nothing to extract. So there is
**one generic text path** (read bytes → decode) that covers every language
forever, including ones we did not list. We deliberately did NOT write
per-language parsers. Only binary/structured formats need a real parser.

| Kind | Formats | How |
|---|---|---|
| Plain text (stdlib) | `.txt .md .csv .tsv .json .yaml .xml .html .css .log .tex` + all code (`.py .js .ts .jsx .tsx .c .cpp .h .java .cs .go .rs .rb .php .sh .sql .r .kt .swift .lua` …) | read bytes → decode (utf-8 → utf-16 → latin-1 → replace) |
| PDF | `.pdf` | `pypdf` |
| Word | `.docx` | `python-docx` (paragraphs + tables) |
| PowerPoint | `.pptx` | `python-pptx` (slides + tables) — also sets up the future "convert presentations" feature |
| Excel | `.xlsx .xlsm` | `openpyxl` (all sheets, values only) |

## Context strategy: hybrid (option C)

- Extracted text ≤ **8,000 chars** → **inlined** into the message under a
  `--- [doc N] filename ---` header. Works with ANY model, no tools needed.
- Longer → **not** inlined; the message carries a note telling the model to use
  the **`read_document`** tool (code mode) with `doc=N`, `offset`, `limit`.
  The tool returns a slice plus a "more remains — call again with offset=X" hint.

**Known limitation:** the tool path requires code mode, because tools are
strictly code-mode-gated in this app. A large document attached in *casual*
mode can only be inlined up to the cap. Acceptable for now; revisit if needed.

## Decisions (agreed with user 2026-10-13)

- Hybrid inline/tool (option C), pure-Python parsers.
- XLSX **and** CSV both in scope.
- Code files handled as text, not per-language parsers.
- UI: clicking `[+]` fades in two icon buttons `[ img | doc ]` (SVG icons, same
  size); image option only shown when the model supports vision, doc option
  always available.
- Numbering: `[doc N]` per-conversation, separate from `[image N]`, both
  restart at 1 each conversation.

## Implementation

- `backend/documents.py` (new) — `extract(path, filename)` → `{text, kind, meta,
  truncated}`; lazy imports so a missing lib degrades to a clear message;
  400k-char hard cap.
- `backend/store.py` — `attachments` gains `kind`, `text`, `meta` columns
  (+ migration); `add_attachment`/`get_attachment`/`get_messages` carry them;
  new `get_attachments_for_conversation`; `attach_to_message` now assigns
  **per-kind** idx so `[image N]` and `[doc N]` never mix.
- `backend/main.py` — upload accepts documents (extract + store text);
  `read_document` tool added to `TOOLS`; `read_document_slice()` helper;
  chat handler labels `[doc N]`, inlines short docs, defers long ones.
- `frontend/src/components/Composer.jsx` — `[+]` picker with fade-in
  `[ img | doc ]` SVG buttons; separate accept-filtered inputs; doc chips.
- `frontend/src/components/ChatView.jsx` — doc chips in the user bubble.
- `frontend/src/App.jsx` — per-kind chip indices.
- `frontend/src/index.css` — picker menu, fade animation, doc chip styles.
- `backend/requirements.txt` — added pypdf, python-docx, python-pptx, openpyxl.

## Acceptance checklist

- [x] text/code file inlines with `[doc N]` label (no parser)
- [x] PDF / DOCX / PPTX / XLSX extract text
- [x] short doc inlined; long doc deferred to `read_document`
- [x] `read_document` slices with offset/limit + continuation hint
- [x] `[doc N]` numbering per-conversation, separate from `[image N]`
- [x] stored idx matches labels (image 1, doc 1, doc 2 …)
- [x] images + documents in one message
- [x] unsupported type rejected (415)
- [x] deleting a conversation removes doc files + rows
- [x] frontend builds; backend syntax clean
- [ ] live UI click-through (user, via desktop.py)

## Not verified
- Live UI (the `[+]` fade-in, doc chips, drag-drop of a real PDF).
- Windows parity (deferred by user) — deps are pure-Python, so should be fine.
- `read_document` against a real tools-capable model (tested via stub only).

## Follow-up (2026-10-13): app-wide drag & drop

Drag-and-drop was already wired on the composer box from Tier 1, but three gaps
were closed:

1. **App-wide drop target** — dropping files anywhere in the window now attaches
   them (window-level `dragenter/dragover/drop` handlers → `addFiles`).
2. **Navigation guard** — the window handlers always `preventDefault` on
   file drags, so the pywebview shell never navigates to a dropped `file://`
   (which would have replaced the whole UI). This was a real latent bug.
3. **Full-window overlay** — a terminal-styled `[ drop files to attach ]` hint
   fades in while dragging, so it is obvious the whole window accepts drops.

The composer's own drag handlers were removed (the window handler covers it);
the `[+]` picker and paste still work as before. `addFilesRef` keeps the
window listener calling the latest `addFiles` without re-binding on every render.

### Fix v2 (2026-10-13, after live test)

Live test showed the first attempt did NOT work: dropping an image opened it
full-screen (webview navigated to the file), and dropping on the textarea
inserted the file path. Root cause: bubble-phase `window` listeners run
*after* the target's default action, so `preventDefault` came too late in
WebKitGTK. Fixes:

- Listeners moved to **capture phase on `document`** (`{capture: true}`), which
  runs top-down before any target can act — `preventDefault` now reliably
  cancels the native default. Added `stopPropagation()` on drop.
- Belt-and-suspenders `onDragOver`/`onDrop` guards directly on the textarea.

### Esc + debug (2026-10-13)

- **Esc-to-close-picker was added then REMOVED** (same day): the `[+]` picker
  already closes on click-outside and on picking an option, so a dedicated Esc
  path never came into play. Reverted to the original Esc behavior (clear text
  + close picker) — no dead code.
- **DnD debug logging** gated on `SU1RA_DEBUG=1` (also sets
  `window.__SU1RA_DEBUG__` in the served HTML). Logs `dragenter`/`drop` with
  `dataTransfer.types`, file names, and target tag. Purpose: distinguish a
  compositor problem (no `Files` type delivered — likely under Wayland/Hyprland)
  from a handler problem (event arrives but navigation still happens).
  Run: `SU1RA_DEBUG=1 python desktop.py`, then check the webview console.

  **Correction (2026-10-13):** the logs go to the webview console, not stdout,
  so they were invisible in kitty. Added `POST /api/client-log`; the frontend
  debug helper now also POSTs each line, and the backend prints it to the
  terminal as `[su1ra:dnd] ...`. So with `SU1RA_DEBUG=1 python desktop.py`
  (env var on the SAME line as the command — a bare `SU1RA_DEBUG=1` line in
  bash does nothing), DnD diagnostics appear directly in kitty.

### Open question: Hyprland / Wayland DnD

Wayland DnD into WebKitGTK (pywebview's Linux backend, often via XWayland) is a
known weak spot. If the debug log shows **no `drop` event at all**, the
compositor never delivered the file and no frontend fix will help — the fix
would be native (pywebview/desktop.py) or a fallback (e.g. a "browse" button,
which already works via `[+]`). If the log shows a `drop` with files but the
image still opens, it is a handler issue we can chase.

### Fix v3 (2026-10-13, after debug log) — Wayland `text/uri-list` drops

The debug log settled it:

    [su1ra:dnd] dragenter ["text/uri-list","text/html"] target= DIV

Hyprland/Wayland delivers the drag as **`text/uri-list`**, NOT the
browser-standard `Files`. So `hasFiles()` was false → no `preventDefault` →
WebKitGTK opened the image (and the textarea inserted the URI). Not a handler
bug — a different drag flavour.

Fixes:
- `isFileDrag()` now accepts **`Files` OR `text/uri-list`**, and we
  `preventDefault` on either, so the webview never navigates.
- When the drop has no `File` objects (URI-only), parse the `file://` URIs from
  `dataTransfer.getData('text/uri-list')` and hand the **paths** to the backend.
- New `POST /api/attachments/from-path` reads the file from disk (the webview
  cannot read a Wayland-dropped file itself). Handles `file://` prefix and
  URL-encoding.
- `_store_attachment()` shared by both upload endpoints; MIME inferred from the
  extension when a path drop carries none (fixes images being rejected as
  "unsupported file type").
- Verified: image by path, `file://` URI, and code file by path all import
  correctly; missing file → 404.

### Fix v4 (2026-10-13, after second debug log) — native pywebview drop hook

Second live test showed the drop was now *caught* (no full-screen open) but:

    [su1ra:dnd] drop types= ["text/uri-list","text/html"] files= 0 names= [] uris= []

`uris= []` — WebKitGTK advertises `text/uri-list` but `getData()` returns
**empty** on Wayland. So the path is not reachable from the DOM at all.

Root cause + fix found in pywebview's own GTK backend
(`webview/platforms/gtk.py::on_drag_data`): it reads the real paths from the
GTK drag data, but **only when `_dnd_state['num_listeners'] > 0`** — i.e. only
when a DOM `drop` listener is registered through pywebview's DOM API. It then
attaches `pywebviewFullPath` to each dropped file.

- `desktop.py`: `window.events.loaded += _register_native_drop`, which does
  `window.dom.document.events.drop += lambda e: None`. This flips the listener
  count so pywebview captures paths. No-op on Windows/macOS.
- Frontend drop handler: prefer `file.pywebviewFullPath` when present, send it
  to `/api/attachments/from-path`; fall back to `Files`, then `text/uri-list`.
- Verified the pywebview DOM API shape in isolation (DOM.document, Element.events,
  DOMEvent.__iadd__, Element.on all present; `_dnd_state` gates on num_listeners).
- NOT yet verified live — needs another run.

### Fix v5 (2026-10-13, after third debug log) — read `_dnd_state` directly

Third live test: hook registered, but drop still `files= 0` and no
`pywebviewFullPath`. Reason (from `webview/util.py`): pywebview forwards the
captured paths by iterating **`dataTransfer.files`** and matching by name — but
on Wayland that array is empty, so the loop never runs and the paths never
reach JS. The paths ARE captured in Python (`_dnd_state['paths']`), they just
have no way out.

Fix: bypass the broken forwarding entirely.
- `desktop.py`: a `NativeDrop` JS-API class with `takePaths()` that returns and
  clears `webview.dom._dnd_state['paths']`; passed as `js_api=NativeDrop()` to
  `create_window` (defined BEFORE `create_window` — it was initially after,
  which would have been a NameError).
- Frontend drop handler: after `Files`/`pywebviewFullPath` fail, `await
  window.pywebview.api.takePaths()` and import those paths via
  `/api/attachments/from-path`.
- Verified in isolation: `_dnd_state` importable, `takePaths` is the only
  exposed public method, and the read-and-clear logic returns the paths.
- **VERIFIED LIVE (2026-10-13):** dragging a screenshot on Hyprland logs
  `using native takePaths ["/home/ganpat/Pictures/Screenshots/...png"]` then
  `addFiles ... (path: ...)` — the image attaches as a chip. Drag & drop works
  on Wayland.

### Final DnD design (summary)

Three sources tried in order, first hit wins:
1. `dataTransfer.files` with `pywebviewFullPath` (Windows/macOS, and Linux when
   the compositor delivers real `Files`).
2. `dataTransfer.files` (standard browsers).
3. `window.pywebview.api.takePaths()` — reads `webview.dom._dnd_state['paths']`,
   populated by pywebview's GTK `on_drag_data` handler. This is the Wayland path.
   Then `text/uri-list` as a last resort.

All file sources funnel into `addFiles`; path-based ones go through
`POST /api/attachments/from-path`. The `[+]` picker and paste are unaffected.







