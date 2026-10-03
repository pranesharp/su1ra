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
            """
        )
        columns = [r["name"] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()]
        if "context_length" not in columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN context_length INTEGER NOT NULL DEFAULT 0")
        msg_columns = [r["name"] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "stats" not in msg_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN stats TEXT")
        if "tool_calls" not in msg_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN tool_calls TEXT")


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


def _conversation_dict(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "model": row["model"],
        "system_prompt": row["system_prompt"],
        "temperature": row["temperature"],
        "context_length": row["context_length"],
        "created_at": row["created_at"],
    }


def list_conversations():
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM conversations ORDER BY created_at DESC, id DESC").fetchall()
        return [_conversation_dict(r) for r in rows]


def create_conversation(title="", model="", system_prompt="", temperature=0.7, context_length=0):
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO conversations (title, model, system_prompt, temperature, context_length) VALUES (?, ?, ?, ?, ?)",
            (title, model, system_prompt, temperature, context_length),
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
        if k in ("title", "model", "system_prompt", "temperature", "context_length") and v is not None
    }
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
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cursor.rowcount > 0


def get_messages(conversation_id):
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, role, content, stats, tool_calls, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "role": r["role"],
                "content": r["content"],
                "stats": json.loads(r["stats"]) if r["stats"] else None,
                "tool_calls": json.loads(r["tool_calls"]) if r["tool_calls"] else None,
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
            "created_at": row["created_at"],
        }


def delete_message_and_following(message_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT conversation_id FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ? AND id >= ?",
            (row["conversation_id"], message_id),
        )
        return True
