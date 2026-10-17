import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_DB = PROJECT_ROOT / "data" / "app.db"


def _data_dir():
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "su1ra"


DATA_DIR = _data_dir()
DB_PATH = DATA_DIR / "app.db"
ATTACHMENTS_DIR = DATA_DIR / "attachments"

PROMPT_FILENAME = "sysp.txt"
PROMPT_FILE = DATA_DIR / "system-prompt.txt"


def bundled_prompt_path():
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = PROJECT_ROOT
    return base / PROMPT_FILENAME


def bundled_system_prompt():
    try:
        return bundled_prompt_path().read_text(encoding="utf-8")
    except OSError:
        return ""


def _connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    if not DB_PATH.exists() and LEGACY_DB.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LEGACY_DB, DB_PATH)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                system_prompt TEXT NOT NULL DEFAULT '',
                temperature REAL NOT NULL DEFAULT 0.7,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                message_id INTEGER REFERENCES messages(id) ON DELETE CASCADE,
                filename TEXT NOT NULL DEFAULT '',
                mime TEXT NOT NULL DEFAULT '',
                size INTEGER NOT NULL DEFAULT 0,
                path TEXT NOT NULL DEFAULT '',
                idx INTEGER NOT NULL DEFAULT 0,
                kind TEXT NOT NULL DEFAULT 'image',
                text TEXT,
                meta TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id);
            CREATE INDEX IF NOT EXISTS idx_attachments_conversation ON attachments(conversation_id);
            CREATE TABLE IF NOT EXISTS resource_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                items TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                fulfilled_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_resource_requests_conversation ON resource_requests(conversation_id);
            """
        )
        columns = [r["name"] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()]
        if "context_length" not in columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN context_length INTEGER NOT NULL DEFAULT 0")
        if "think" not in columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN think TEXT")
        msg_columns = [r["name"] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "stats" not in msg_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN stats TEXT")
        if "tool_calls" not in msg_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN tool_calls TEXT")
        att_columns = [r["name"] for r in conn.execute("PRAGMA table_info(attachments)").fetchall()]
        if "kind" not in att_columns:
            conn.execute("ALTER TABLE attachments ADD COLUMN kind TEXT NOT NULL DEFAULT 'image'")
        if "text" not in att_columns:
            conn.execute("ALTER TABLE attachments ADD COLUMN text TEXT")
        if "meta" not in att_columns:
            conn.execute("ALTER TABLE attachments ADD COLUMN meta TEXT")
        # Per-conversation mode (v0.3.1): which desk a chat belongs to — build
        # or casual. Never persisted before, so opening an old build chat
        # could not restore the mode. 0 = casual, 1 = build.
        conv_columns = {r[1] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()}
        if "code_mode" not in conv_columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN code_mode INTEGER NOT NULL DEFAULT 0")

        # Seed / refresh the bundled system prompt:
        # - NULL means "never set" -> insert bundled.
        # - An explicitly cleared ("") default is left alone.
        # - A pristine default (still equal to the last bundled text we
        #   applied) follows bundled updates, so reinstalls/updates pick
        #   up a new sysp.txt without wiping chats.
        # - A user-customized default (differs from the last bundled text)
        #   is preserved; only the marker advances.
        # The marker key tracks the last bundled text we have seen, so we
        # can tell "pristine but stale" apart from "customized".
        row = conn.execute("SELECT value FROM settings WHERE key = 'default_system_prompt'").fetchone()
        marker = conn.execute(
            "SELECT value FROM settings WHERE key = 'default_system_prompt_bundled'"
        ).fetchone()
        bundled = bundled_system_prompt()
        if bundled.strip():
            if row is None:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('default_system_prompt', ?)",
                    (bundled,),
                )
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('default_system_prompt_bundled', ?)",
                    (bundled,),
                )
            elif marker is None:
                # Upgrade path: DBs created before the marker existed.
                # Push the new bundled text unless the user explicitly
                # cleared the default.
                current = row["value"]
                if current != "":
                    if current != bundled:
                        conn.execute(
                            "UPDATE settings SET value = ? WHERE key = 'default_system_prompt'",
                            (bundled,),
                        )
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('default_system_prompt_bundled', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (bundled,),
                )
            elif marker["value"] != bundled:
                current = row["value"]
                if current == marker["value"]:
                    conn.execute(
                        "UPDATE settings SET value = ? WHERE key = 'default_system_prompt'",
                        (bundled,),
                    )
                # Empty ("") and customized values are preserved here.
                conn.execute(
                    "UPDATE settings SET value = ? WHERE key = 'default_system_prompt_bundled'",
                    (bundled,),
                )
        # One-time normalization (guarded by marker): older builds STAMPED the
        # global default into every new conversation's per-chat system_prompt,
        # which made the bundled build prompt leak into casual mode (per-chat
        # overrides win over mode defaults). Clear stamps that are byte-equal
        # to a bundled default we shipped (old marker or the new text);
        # genuine custom prompts differ and survive. Also backfill code_mode:
        # only build chats ever produced tool messages.
        norm = conn.execute("SELECT value FROM settings WHERE key = 'perchat_sysp_norm'").fetchone()
        if not norm and bundled.strip():
            old_marker = marker["value"] if marker else ""
            conn.execute(
                "UPDATE conversations SET system_prompt = '' WHERE system_prompt = ?",
                (bundled,),
            )
            if old_marker and old_marker != bundled:
                conn.execute(
                    "UPDATE conversations SET system_prompt = '' WHERE system_prompt = ?",
                    (old_marker,),
                )
            conn.execute(
                "UPDATE conversations SET code_mode = 1 WHERE id IN "
                "(SELECT DISTINCT conversation_id FROM messages WHERE role = 'tool')"
            )
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('perchat_sysp_norm', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (bundled,),
            )


def get_setting(key):
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(key, value):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


THINK_VALUES = ("on", "off", "low", "medium", "high", "max")


def normalize_think(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "on" if value else "off"
    text = str(value).strip().lower()
    if text in ("", "auto", "default", "none"):
        return None
    if text in THINK_VALUES:
        return text
    raise ValueError(f"think must be auto/on/off (got {value!r})")


def _conversation_dict(row):
    keys = set(row.keys())
    return {
        "id": row["id"],
        "title": row["title"],
        "model": row["model"],
        "system_prompt": row["system_prompt"],
        "temperature": row["temperature"],
        "context_length": row["context_length"],
        "think": row["think"] if "think" in keys else None,
        "code_mode": bool(row["code_mode"]) if "code_mode" in keys else False,
        "created_at": row["created_at"],
    }


def list_conversations():
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM conversations ORDER BY created_at DESC, id DESC").fetchall()
        return [_conversation_dict(r) for r in rows]


def create_conversation(title="", model="", system_prompt="", temperature=0.7, context_length=0, think=None, code_mode=False):
    think = normalize_think(think)
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO conversations (title, model, system_prompt, temperature, context_length, think, code_mode) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, model, system_prompt, temperature, context_length, think, 1 if code_mode else 0),
        )
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _conversation_dict(row)


def get_conversation(conversation_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        return _conversation_dict(row) if row else None


def update_conversation(conversation_id, **fields):
    allowed = {
        k: v
        for k, v in fields.items()
        if k in ("title", "model", "system_prompt", "temperature", "context_length", "code_mode") and v is not None
    }
    if "think" in fields:
        allowed["think"] = normalize_think(fields["think"])
    if "code_mode" in allowed:
        allowed["code_mode"] = 1 if allowed["code_mode"] else 0
    if not allowed:
        return get_conversation(conversation_id)
    sets = ", ".join(f"{k} = ?" for k in allowed)
    with _connect() as conn:
        conn.execute(
            f"UPDATE conversations SET {sets} WHERE id = ?",
            (*allowed.values(), conversation_id),
        )
    return get_conversation(conversation_id)


def delete_conversation(conversation_id):
    delete_attachment_files_for_conversation(conversation_id)
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cursor.rowcount > 0


def get_messages(conversation_id):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, role, content, stats, tool_calls, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        att_rows = conn.execute(
            "SELECT id, message_id, filename, mime, size, idx, kind, meta FROM attachments "
            "WHERE conversation_id = ? AND message_id IS NOT NULL ORDER BY idx, id",
            (conversation_id,),
        ).fetchall()
        by_message = {}
        for a in att_rows:
            by_message.setdefault(a["message_id"], []).append(_attachment_dict(a))
        return [
            {
                "id": r["id"],
                "role": r["role"],
                "content": r["content"],
                "stats": json.loads(r["stats"]) if r["stats"] else None,
                "tool_calls": json.loads(r["tool_calls"]) if r["tool_calls"] else None,
                "attachments": by_message.get(r["id"], []),
                "created_at": r["created_at"],
            }
            for r in rows
        ]


def add_message(conversation_id, role, content, stats=None, tool_calls=None):
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, stats, tool_calls) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, json.dumps(stats) if stats else None, json.dumps(tool_calls) if tool_calls else None),
        )
        row = conn.execute(
            "SELECT id, role, content, stats, tool_calls, created_at FROM messages WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "stats": json.loads(row["stats"]) if row["stats"] else None,
            "tool_calls": json.loads(row["tool_calls"]) if row["tool_calls"] else None,
            "attachments": [],
            "created_at": row["created_at"],
        }


def _attachment_dict(row):
    keys = set(row.keys())
    d = {
        "id": row["id"],
        "message_id": row["message_id"] if "message_id" in keys else None,
        "filename": row["filename"],
        "mime": row["mime"],
        "size": row["size"],
        "idx": row["idx"],
    }
    if "kind" in keys:
        d["kind"] = row["kind"]
    if "meta" in keys:
        d["meta"] = json.loads(row["meta"]) if row["meta"] else None
    return d


def add_attachment(conversation_id, filename, mime, size, path, kind="image", text=None, meta=None):
    """Register a stored attachment file. message_id is NULL until it is sent."""
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO attachments (conversation_id, filename, mime, size, path, kind, text, meta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (conversation_id, filename, mime, size, path, kind, text, json.dumps(meta) if meta else None),
        )
        row = conn.execute(
            "SELECT id, message_id, filename, mime, size, idx, kind, meta FROM attachments WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return _attachment_dict(row)


def get_attachments_for_conversation(conversation_id):
    """All attachments in a conversation — LINKED rows first in their per-chat
    idx order (the numbers the model saw as [doc N] / [image N]), then still-
    pending rows (idx=0) in insertion order. read_document_slice numbers
    documents from this list, so its doc N must equal the labeled [doc N]."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, message_id, filename, mime, size, idx, kind, meta FROM attachments "
            "WHERE conversation_id = ? ORDER BY (idx = 0), idx, id",
            (conversation_id,),
        ).fetchall()
        return [_attachment_dict(r) for r in rows]


def get_attachment(attachment_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, conversation_id, message_id, filename, mime, size, path, idx, kind, text, meta "
            "FROM attachments WHERE id = ?",
            (attachment_id,),
        ).fetchone()
        if not row:
            return None
        d = _attachment_dict(row)
        d["conversation_id"] = row["conversation_id"]
        d["path"] = row["path"]
        d["text"] = row["text"]
        return d


def attach_to_message(attachment_ids, message_id, conversation_id):
    """Link pending attachments to a sent message, assigning a per-kind,
    per-conversation idx (1-based, in the order given) so [image N] / [doc N]
    numbering is per-conversation and never mixes the two kinds. Counters are
    seeded from the highest idx already linked in the chat, so a SECOND batch
    of docs/images continues the numbers — read_document lists documents
    conversation-wide and would otherwise collide across batches."""
    if not attachment_ids:
        return []
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, kind FROM attachments WHERE conversation_id = ? AND message_id IS NULL",
            (conversation_id,),
        ).fetchall()
        kind_of = {r["id"]: (r["kind"] or "image") for r in rows}
        counters = {
            (r["kind"] or "image"): (r["m"] or 0)
            for r in conn.execute(
                "SELECT kind, MAX(idx) AS m FROM attachments "
                "WHERE conversation_id = ? AND message_id IS NOT NULL GROUP BY kind",
                (conversation_id,),
            ).fetchall()
        }
        linked = []
        for aid in attachment_ids:
            if aid not in kind_of:
                continue
            kind = kind_of[aid]
            counters[kind] = counters.get(kind, 0) + 1
            conn.execute(
                "UPDATE attachments SET message_id = ?, idx = ? WHERE id = ?",
                (message_id, counters[kind], aid),
            )
            linked.append(aid)
        return linked


def max_attachment_idx(conversation_id, kind):
    """Highest per-conversation idx already linked for a kind (0 when none).
    The single source of truth for where the next [doc N] / [image N] starts —
    the chat handler's label math and attach_to_message's counters both use it
    so labels and stored idx can never drift apart."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT MAX(idx) AS m FROM attachments "
            "WHERE conversation_id = ? AND kind = ? AND message_id IS NOT NULL",
            (conversation_id, kind),
        ).fetchone()
        return (row["m"] or 0) if row else 0


# --- Resource requests (request_resources tool + the /web cart) ---------------

def _resource_request_dict(row):
    return {
        "id": row["id"],
        "conversation_id": row["conversation_id"],
        "items": json.loads(row["items"]) if row["items"] else [],
        "created_at": row["created_at"],
        "fulfilled_at": row["fulfilled_at"],
    }


def create_resource_request(conversation_id, items):
    """Record a pending request_resources ask. items: list of {topic, why, search_hint?}."""
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO resource_requests (conversation_id, items) VALUES (?, ?)",
            (conversation_id, json.dumps(items)),
        )
        row = conn.execute(
            "SELECT id, conversation_id, items, created_at, fulfilled_at FROM resource_requests WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return _resource_request_dict(row)


def get_pending_resource_request(conversation_id):
    """The conversation's latest un-fulfilled resource request, or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, conversation_id, items, created_at, fulfilled_at FROM resource_requests "
            "WHERE conversation_id = ? AND fulfilled_at IS NULL ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return _resource_request_dict(row) if row else None


def fulfill_resource_request(conversation_id):
    """Close every open resource request in a conversation. Returns count closed."""
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE resource_requests SET fulfilled_at = datetime('now') "
            "WHERE conversation_id = ? AND fulfilled_at IS NULL",
            (conversation_id,),
        )
        return cursor.rowcount


def delete_attachment_files_for_conversation(conversation_id):
    """Remove on-disk attachment files for a conversation (rows cascade)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT path FROM attachments WHERE conversation_id = ?", (conversation_id,)
        ).fetchall()
    for r in rows:
        try:
            Path(r["path"]).unlink(missing_ok=True)
        except OSError:
            pass


def delete_message_and_following(message_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT conversation_id FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not row:
            return False
        conv_id = row["conversation_id"]
        paths = [
            r["path"]
            for r in conn.execute(
                "SELECT path FROM attachments WHERE conversation_id = ? AND message_id >= ?",
                (conv_id, message_id),
            ).fetchall()
        ]
        conn.execute(
            "DELETE FROM attachments WHERE conversation_id = ? AND message_id >= ?",
            (conv_id, message_id),
        )
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ? AND id >= ?",
            (conv_id, message_id),
        )
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass
    return True


def clear_conversation_messages(conversation_id):
    """Drop every message in a conversation, keeping the conversation itself."""
    delete_attachment_files_for_conversation(conversation_id)
    with _connect() as conn:
        # Attachment rows are only cascade-deleted when the conversation goes,
        # so drop them explicitly here too — otherwise they linger with a
        # dangling message_id and a path to a file we just unlinked.
        conn.execute("DELETE FROM attachments WHERE conversation_id = ?", (conversation_id,))
        n = conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        ).rowcount
        conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", ("", conversation_id)
        )
        return n


def delete_all_conversations():
    with _connect() as conn:
        paths = [r["path"] for r in conn.execute("SELECT path FROM attachments").fetchall()]
        n = conn.execute("DELETE FROM conversations").rowcount
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass
    return n
