# Task: Image import (Tier 1 of file-import feature)

Status: BUILT (2026-10-13) — backend + frontend done, builds clean, verified
live by the user (image attach + drag & drop on Hyprland).
Tier 1 only — images. Tier 2 (documents) was built the same day; see
`document-import-task.md`. Tier 3 (video) is parked — see `fplan.md`.

## Why / scope

User wants to attach images to a chat message so a vision model can see them,
with multiple images per message and stable per-session numbering (`[image 1]`,
`[image 2]`, ...) that the user can reference in prose ("I have this [image 1]
and I want this [image 2]"). New sessions must restart at `image 1` — no
carry-over numbering from past chats.

Out of scope this round (discussed, deferred):
- Tier 2 documents: PDF / Word / text / code (pure-Python parsers, inline-with-cap
  vs. retrieval-tool decision) — user OK with py libs, discuss later.
- Tier 3 video: parked 2026-10-13 — options (frame extraction / scene detection /
  whisper transcription / hybrid) captured in `fplan.md`; awaiting use case.

## Decisions (agreed with user 2026-10-13)

- **Storage**: files on disk under `DATA_DIR/attachments/<uuid>.<ext>`; DB stores
  only a reference row. Prevents DB bloat AND keeps files present when revisiting
  old chats (explicit user requirement). Conversation delete removes its files.
- **Numbering**: per-conversation `img N`, derived from message order within that
  conversation — every session starts at 1. Label injected into the message text
  as `[image N]` so the model can correlate prose references to specific images.
- **Context strategy**: inline, always. Image bytes go to Ollama's native
  `images` field on the user message. (The inline-vs-tool choice only applies to
  documents later; images have no sensible retrieval-tool path.)
- **Vision gate**: only offer attachment when the model advertises `vision` in
  `/api/show` capabilities (extends existing `model_supports_tools` detection).
- **UI**: `[+]` button left of the composer input; picked images render as
  thumbnail chips ABOVE the textarea, right-aligned, each with a small
  `[image N]` heading. User bubbles render their thumbnails too.

## Implementation plan

1. `backend/store.py`
   - `attachments` table: `id, conversation_id, message_id (nullable until sent),
     filename, mime, size, path, idx, created_at` + FK cascade on conversation.
   - helpers: `add_attachment`, `attach_to_message`, `get_attachments_for_message`,
     `get_attachments_for_conversation`, `delete_attachment_files_for_conversation`.
   - `get_messages` joins attachment refs onto each message.
2. `backend/ollama.py`
   - `model_supports_vision(model)` mirroring `model_supports_tools` (cache).
   - `stream_chat` already forwards `messages`; ensure `images` on a message pass
     through untouched (they do — payload_messages = system + messages).
3. `backend/main.py`
   - `POST /api/attachments` (multipart or base64 JSON) → save file, return ref.
   - `GET /api/attachments/{id}` → serve the file (for thumbnails in old chats).
   - `ChatRequest.attachment_ids: list[int]`; on chat, load refs, base64 them,
     attach to the user message as `images`, link rows to the message id, and
     prefix the content with `[image N]` labels.
   - `DELETE /api/conversations/{id}` also unlinks attachment files.
   - `/api/models` (or a new `/api/model/caps`) exposes vision capability so the
     UI can gate the `[+]`.
4. `frontend/src/components/Composer.jsx`
   - `[+]` button, hidden file input, drag-drop + paste handlers.
   - thumbnail chips above textarea with `[image N]` headings, remove button.
   - numbering is local to the pending set (1..n) and matches send order.
5. `frontend/src/App.jsx`
   - hold pending attachments; upload on pick (or on send); pass `attachment_ids`
     to `streamChat`; clear after send.
6. `frontend/src/components/ChatView.jsx`
   - render thumbnails in the user bubble from `m.attachments`.
7. `frontend/src/api.js` — `uploadAttachment`, `attachmentUrl`.
8. CSS in `index.css` — chips, thumbnails, `[+]` button.

## Acceptance checklist

- [x] `[+]` appears only when the selected model supports vision
- [x] pick / drag-drop / paste all add a thumbnail chip with `[image N]`
- [x] multiple images in one message; prose can reference `[image 1]`/`[image 2]`
- [x] send: model receives images, answers about them (verified via stub: 2 images, labeled content)
- [x] numbering restarts at 1 in a new conversation
- [x] reopening an old chat shows its thumbnails (files still on disk)
- [x] deleting a conversation removes its attachment files
- [x] non-vision model: no `[+]`, no images sent
- [x] Windows parity: no new native deps (pure Python + browser APIs only)
- [ ] live UI click-through (user, via desktop.py)

## Implementation notes / deviations

- **Upload transport changed from multipart to base64 JSON.** FastAPI's
  `Form`/`File` needs `python-multipart`, which is not installed and would be a
  new dependency. `POST /api/attachments` now takes JSON
  `{conversation_id, filename, mime, data(base64)}` — reuses the existing
  `sendJSON` helper, zero new deps. Frontend reads the file via `FileReader`.
- **Label ordering fix:** labels are computed and prefixed into `content`
  BEFORE `add_message`, so the persisted row and the history sent to Ollama
  both carry `[image N]`. (First attempt labeled after insert → DB/model missed
  the prefix; caught by the end-to-end test.)
- **Images are sent on the turn they are attached only.** Prior turns' images
  are not re-sent on later turns (they are not stored as base64 in the DB
  content). Acceptable for Tier 1; revisit if multi-turn image memory is wanted.
- **Files**: `DATA_DIR/attachments/<uuid>.<ext>`; DB `attachments` table holds
  the reference + per-conversation `idx`. Conversation delete / clear / message
  truncation unlink the files.
- **Cleanup bug found + fixed (2026-10-13, live-test follow-up):** attachment
  rows are only cascade-deleted when the *conversation* is deleted, so `/clear`
  and edit/redo truncation were unlinking the files but leaving orphan rows
  (dangling `message_id`, path to a deleted file). Added explicit
  `DELETE FROM attachments ...` in `clear_conversation_messages` and
  `delete_message_and_following`. All four paths (delete conversation, clear,
  edit/redo, clear-all) now remove both file and row — verified.
- **Caps endpoint**: `GET /api/model/caps?model=` returns `{tools, vision}`;
  frontend probes it on model change to gate `[+]`.

## Files touched

- `backend/store.py` — attachments table + helpers, message join, cleanup hooks
- `backend/ollama.py` — `model_supports_vision`
- `backend/main.py` — `AttachmentUpload`, `attachment_ids` on `ChatRequest`,
  `POST /api/attachments`, `GET /api/attachments/{id}`, `GET /api/model/caps`,
  chat handler image wiring
- `frontend/src/api.js` — `getModelCaps`, `attachmentUrl`, `uploadAttachment`
- `frontend/src/components/Composer.jsx` — `[+]`, drag-drop, paste, chips
- `frontend/src/components/ChatView.jsx` — thumbnails in user bubble
- `frontend/src/App.jsx` — pending attachments, vision probe, send wiring
- `frontend/src/index.css` — attachment styles

## Notes

- No new Python dependencies for Tier 1 (stdlib + existing httpx/fastapi).
- Verify live by running `desktop.py` (user does this) — backend serves built UI
  on :8000.
