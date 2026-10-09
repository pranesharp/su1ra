"""Workspace: the one folder-tree the model may touch (code mode only).

Boundary = workspace root (a /code-loadout setting, default
~/Documents/su1ra_projects). Every file tool resolves through safe_join:
absolute resolution + symlink resolution must stay inside the root, or the
call is denied. There is deliberately no delete/rename tool — the model
can create and edit, never destroy; the user deletes.

The model's working directory is the active project (a conversation-level
setting naming one child of the root). Relative tool paths resolve there;
`../sibling` inside the root is allowed, escaping the root is not.
"""
import os
from pathlib import Path

from store import get_setting

MAX_READ_CHARS = 24000
MAX_WRITE_CHARS = 200000
MAX_LS_ENTRIES = 200


def default_root():
    docs = Path.home() / "Documents"
    return docs / "su1ra_projects"


def root():
    configured = (get_setting("workspace_root") or "").strip()
    base = Path(configured).expanduser() if configured else default_root()
    return base


def active_project():
    return (get_setting("active_project") or "").strip()


def _base():
    return root().resolve()


def _proj(base):
    name = active_project()
    if not name:
        return base
    p = (base / name).resolve()
    if p != base and base not in p.parents:
        raise ValueError(f"denied: active project {name!r} escapes the workspace")
    return p


def project_dir():
    """Absolute dir tools resolve relative paths against."""
    return _proj(_base())


def resolve(user_path):
    """Resolve user_path inside the workspace root. Raises ValueError if
    it escapes (.., absolute paths elsewhere, symlink breakouts)."""
    base = _base()
    text = "" if user_path is None else str(user_path).strip()
    if text in ("", "."):
        return _proj(base)
    p = (_proj(base) / text).resolve()
    if p != base and base not in p.parents:
        raise ValueError(
            f"denied: outside workspace {base} — ask the user in plain "
            "words if you need this, never retry with another spelling"
        )
    return p


def display(path):
    """Workspace-relative display path for tool output (short, stable)."""
    try:
        return str(Path(path).resolve().relative_to(root().resolve()))
    except Exception:
        return str(path)


def ls(user_path=""):
    target = resolve(user_path) if user_path else project_dir()
    if not target.exists():
        return {"ok": False, "error": f"no such directory: {display(target)}"}
    if not target.is_dir():
        return {"ok": False, "error": f"not a directory: {display(target)}"}
    entries = []
    for child in sorted(target.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
        try:
            entries.append({
                "name": child.name,
                "dir": child.is_dir(),
                "size": child.stat().st_size if child.is_file() else 0,
            })
        except OSError:
            continue
        if len(entries) >= MAX_LS_ENTRIES:
            break
    return {"ok": True, "path": display(target), "entries": entries}


def read(user_path):
    try:
        target = resolve(user_path)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not target.exists():
        return {"ok": False, "error": f"no such file: {user_path}"}
    if not target.is_file():
        return {"ok": False, "error": f"not a file: {user_path}"}
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": f"not a text file: {user_path}"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    total = len(text)
    if total > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS]
    return {"ok": True, "path": display(target), "content": text,
            "chars": total, "truncated": total > MAX_READ_CHARS}


def write(user_path, content):
    try:
        target = resolve(user_path)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not isinstance(content, str):
        return {"ok": False, "error": "content must be text"}
    if len(content) > MAX_WRITE_CHARS:
        return {"ok": False, "error": f"content too large ({len(content)} chars, max {MAX_WRITE_CHARS})"}
    if target.exists() and not target.is_file():
        return {"ok": False, "error": f"not a file: {user_path}"}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": display(target), "chars": len(content)}


def edit(user_path, find, replacement):
    try:
        target = resolve(user_path)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not target.is_file():
        return {"ok": False, "error": f"no such file: {user_path}"}
    if not find:
        return {"ok": False, "error": "find string is empty — re-read the file and pick a unique anchor"}
    try:
        text = target.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    count = text.count(find)
    if count == 0:
        return {"ok": False, "error": "anchor not found (0 matches) — re-read the file, copy it exactly"}
    if count > 1:
        return {"ok": False, "error": f"anchor matches {count} places — narrow it to a unique one"}
    try:
        target.write_text(text.replace(find, replacement, 1), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": display(target), "replaced": 1}


def mkdir(user_path):
    """Create a folder at the workspace root (projects live here).

    Root-relative on purpose: `mkdir project_1` makes a project no matter
    which project is active. File tools (ls/read/write/edit) are
    project-relative instead.
    """
    text = "" if user_path is None else str(user_path).strip()
    if not text or text in (".", "/"):
        return {"ok": False, "error": "name a project folder, e.g. project_1"}
    base = _base()
    target = (base / text).resolve()
    if target != base and base not in target.parents:
        return {"ok": False, "error": f"denied: outside workspace {base}"}
    if target.exists():
        if target.is_dir():
            return {"ok": True, "path": display(target), "exists": True}
        return {"ok": False, "error": f"a file already has that name: {text}"}
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": display(target), "exists": False}


def set_active_project(name):
    """Validate + persist the conversation's project dir. Raises ValueError."""
    from store import set_setting

    clean = (name or "").strip().replace("\\", "/").strip("/")
    if not clean or clean in (".", "..") or clean.startswith("../") or "/../" in clean:
        raise ValueError("name a project folder inside the workspace, e.g. project_1")
    base = _base()
    target = (base / clean).resolve()
    if target != base and base not in target.parents:
        raise ValueError("that escapes the workspace")
    if not target.exists():
        raise ValueError(f"no such project: {clean} — /mkdir it first")
    if not target.is_dir():
        raise ValueError(f"not a project folder: {clean}")
    set_setting("active_project", clean)
    return display(target)


def validate_root(value):
    """Validate a workspace-root setting value. Returns absolute str."""
    p = Path(value).expanduser()
    if not p.is_absolute():
        raise ValueError("workspace root must be an absolute path")
    return str(p)
