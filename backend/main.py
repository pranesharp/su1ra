import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

import httpx

import documents
import doc_builders
import gpumon
import ollama
import ollama_setup
import pptx_builder
import puller
import runner
import sandbox
import store
import workspace

if os.name == "posix":
    import ptyrunner

if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST = PROJECT_ROOT / "frontend" / "dist"

store.init_db()

app = FastAPI(title="Su1ra")


@app.on_event("startup")
async def reset_session_settings():
    for key in ("show_stats", "ide_open"):
        store.set_setting(key, "0")
    start_sysmon()
    start_wsl_warm_probe()


# Held reference — asyncio keeps only weak refs to tasks; an unreferenced
# sampler can be garbage-collected mid-execution (classic create_task pitfall).
_sysmon_task = None


def start_sysmon():
    global _sysmon_task
    if _sysmon_task is None or _sysmon_task.done():
        _sysmon_task = asyncio.create_task(sysmon_sampler())


# Held reference — same pitfall as _sysmon_task.
_wsl_probe_task = None


def start_wsl_warm_probe():
    """Windows only: warm the WSL probe cache at boot so the first sandboxed
    tool run doesn't pay the distro cold-start on the model's clock. Best
    effort — a failure here must never break startup."""
    global _wsl_probe_task
    if os.name != "nt" or store.get_setting("sandbox_backend") == "off":
        return
    if _wsl_probe_task and not _wsl_probe_task.done():
        return

    async def _warm():
        try:
            await asyncio.to_thread(sandbox.wsl_probe)
        except Exception:
            pass

    _wsl_probe_task = asyncio.create_task(_warm())


# --- system monitor (btop-lite) ---------------------------------------------
# Tiny sampler feeding /api/sysmon: cpu / ram / disk / gpu utilization as
# 0-100 percents (None = unavailable). Pure stdlib — no psutil, so the frozen
# build needs nothing new. GPUs come from gpumon.py (Windows: WDDM perf
# counters — any vendor incl. Intel iGPU/Vulkan; Linux: AMD sysfs + nvidia-smi)
# as a per-adapter list, integrated GPU first.
SYSMON = {"cpu": None, "ram": None, "disk": None, "gpu": None, "gpus": []}
_cpu_last = None


def _cpu_percent_now():
    """Instantaneous CPU utilization from the delta between two calls of this
    function (the sampler keeps the previous reading in _cpu_last)."""
    global _cpu_last
    try:
        if os.name == "nt":
            import ctypes

            class FT(ctypes.Structure):
                _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]

                def val(self):
                    return (self.hi << 32) | self.lo

            idle, kern, user = FT(), FT(), FT()
            if not ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)
            ):
                return None
            idle_t, total = idle.val(), kern.val() + user.val()
        else:
            with open("/proc/stat") as f:
                parts = f.readline().split()[1:]
            nums = [int(p) for p in parts]
            idle_t = nums[3] + (nums[4] if len(nums) > 4 else 0)
            total = sum(nums)
        if _cpu_last is None:
            _cpu_last = (idle_t, total)
            return None
        d_idle = idle_t - _cpu_last[0]
        d_total = total - _cpu_last[1]
        _cpu_last = (idle_t, total)
        if d_total <= 0:
            return None
        return max(0.0, min(100.0, (1 - d_idle / d_total) * 100))
    except Exception:
        return None


def _ram_percent():
    try:
        if os.name == "nt":
            import ctypes

            class STATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_uint32),
                    ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            st = STATUSEX()
            st.dwLength = ctypes.sizeof(STATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return None
            return float(st.dwMemoryLoad)
        vals = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                if k in ("MemTotal", "MemAvailable"):
                    vals[k] = int(v.strip().split()[0])
        total, avail = vals.get("MemTotal"), vals.get("MemAvailable")
        if not total:
            return None
        return (total - (avail or 0)) / total * 100
    except Exception:
        return None


def _disk_percent():
    try:
        du = shutil.disk_usage(store.DATA_DIR)  # usage(total, used, free)
        if not du.total:
            return None
        return du.used / du.total * 100
    except Exception:
        return None


async def sysmon_sampler():
    while True:
        SYSMON["cpu"] = _cpu_percent_now()
        SYSMON["ram"] = _ram_percent()
        SYSMON["disk"] = _disk_percent()
        # per-adapter list, iGPU first; "gpu" kept as gpus[0] for old clients
        gpus = await asyncio.to_thread(gpumon.sample)
        SYSMON["gpus"] = gpus
        SYSMON["gpu"] = gpus[0]["util"] if gpus else None
        await asyncio.sleep(2)


@app.get("/api/sysmon")
async def sysmon_get():
    return dict(SYSMON)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

RUN_STDIN = {}
RUN_PTY = {}
TIMEOUT_SECONDS = 30
TERM_OUTPUT_CAP = 5 * 1024 * 1024
HAS_PTY = os.name == "posix"

# --- editor run: file-type → interpreter ------------------------------------
# The editor pane saves the buffer to a real file in scratch/ and executes it
# by extension, like a text editor's run button. Interpreters are resolved at
# request time; a missing one is a clean 422, never a crash.

_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,80}$")


def python_exe():
    """A real python interpreter — same resolver the run_python tool uses.
    (Kept as a thin alias: one rule for "never spawn our own exe as a child",
    so the editor path and the tool path cannot drift apart again.)"""
    return runner.python_exe()


def build_run_argv(filename):
    """argv to run scratch/<filename>, or (None, reason) if not runnable."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".py":
        exe = python_exe()
        if not exe:
            return None, "no python interpreter found on this machine"
        return [exe, "-u", filename], {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    if ext in (".js", ".mjs", ".cjs"):
        exe = shutil.which("node")
        if not exe:
            return None, "node is not installed (or not on PATH)"
        return [exe, filename], {}
    if ext in (".sh", ".bash"):
        exe = shutil.which("bash") or shutil.which("sh")
        if not exe:
            return None, "no POSIX shell found on this machine"
        return [exe, filename], {}
    if ext == ".ps1":
        exe = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if not exe:
            return None, "powershell not found"
        return [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", filename], {}
    if ext in (".bat", ".cmd"):
        exe = shutil.which("cmd.exe")
        if not exe:
            return None, "cmd.exe not found"
        return [exe, "/c", filename], {}
    if ext == ".rb":
        exe = shutil.which("ruby")
        if not exe:
            return None, "ruby is not installed (or not on PATH)"
        return [exe, filename], {}
    if ext == ".pl":
        exe = shutil.which("perl")
        if not exe:
            return None, "perl is not installed (or not on PATH)"
        return [exe, filename], {}
    if ext == ".lua":
        exe = shutil.which("lua") or shutil.which("luajit")
        if not exe:
            return None, "lua is not installed (or not on PATH)"
        return [exe, filename], {}
    return None, f".{ext.lstrip('.') or '?'} files are saved but not runnable here"

MAX_TOOL_ROUNDS = 3
MAX_RESULT_CHARS = 12000

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "Execute Python code and return its stdout and stderr. Use this to run, test, or verify Python code. Execution is non-interactive: input() does not work. Keep code self-contained and print the results you want to see.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "The Python code to execute"}
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_ls",
            "description": "List a workspace directory (default: active project). Paths are relative to the active project; ../sibling inside the workspace is allowed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory to list (default: active project)"}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_read",
            "description": "Read a text file from the workspace. Always read a file before editing it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the active project"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_write",
            "description": "Create or overwrite a text file in the workspace. For changes to an existing file prefer ws_edit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the active project"},
                    "content": {"type": "string", "description": "Full file content"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_edit",
            "description": "Replace one exact anchor string in a workspace file. The anchor must match exactly once — check the match count in the result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the active project"},
                    "find": {"type": "string", "description": "Exact anchor text, copied from ws_read"},
                    "replacement": {"type": "string", "description": "New text"},
                },
                "required": ["path", "find", "replacement"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_cd",
            "description": (
                "Switch the active project folder. Use RIGHT AFTER ws_mkdir when starting "
                "a new project (mkdir + cd, then work). Also use to enter an existing "
                "project the user names. A bare name means a folder directly inside the "
                "workspace root. The switch persists and is announced in chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {"project": {"type": "string", "description": "folder name inside the workspace root, e.g. photosynthesis-deck"}},
                "required": ["project"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ws_mkdir",
            "description": "Create a folder at the workspace root (e.g. a new project). Cannot create anything outside the root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Folder to create, e.g. project_1"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": (
                "Read the extracted text of a document the user attached to this chat "
                "(PDF, Word, PowerPoint, Excel, or a text/code file). Use this when a "
                "document is too long to have been shown inline. Documents are labelled "
                "[doc N] in the conversation. Returns a slice of the text; use offset to "
                "read further if the result says there is more."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "doc": {"type": "integer", "description": "The document number N from its [doc N] label"},
                    "offset": {"type": "integer", "description": "Character offset to start at (default 0)"},
                    "limit": {"type": "integer", "description": "Max characters to return (default 8000)"},
                },
                "required": ["doc"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_pptx",
            "description": (
                "Build a real .pptx presentation from a structured outline. ALWAYS prefer "
                "this over writing python-pptx code — it handles layout, fonts and sizing. "
                "The deck is saved in the project folder next to a <name>.preview.html slide "
                "player that opens in the preview pane automatically. Layouts: 'title' "
                "(title+subtitle), 'section' (divider), 'bullets', 'two_col' (left/right "
                "bullet arrays), 'table' (rows: first row is the header), 'image' (path "
                "relative to the project folder; png/jpg/gif/bmp; optional caption). Prefix "
                "a bullet with '> ' to make it an emphasized accent line. Every slide can "
                "carry speaker 'notes'. Revise by calling again with the same filename — "
                "it regenerates in place."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Deck file name, e.g. photosynthesis.pptx"},
                    "theme": {"type": "string", "description": "terminal-dark (default) or clean-light"},
                    "slides": {
                        "type": "array",
                        "description": "Slide outline, in order (max 60)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "layout": {"type": "string", "description": "title | section | bullets | two_col | table | image"},
                                "title": {"type": "string"},
                                "subtitle": {"type": "string", "description": "title layout only"},
                                "bullets": {"type": "array", "items": {"type": "string"}, "description": "bullets layout"},
                                "left": {"type": "array", "items": {"type": "string"}, "description": "two_col left column"},
                                "right": {"type": "array", "items": {"type": "string"}, "description": "two_col right column"},
                                "left_title": {"type": "string", "description": "two_col optional column heading"},
                                "right_title": {"type": "string", "description": "two_col optional column heading"},
                                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}, "description": "table: header row first"},
                                "image": {"type": "string", "description": "image layout: path relative to the project folder"},
                                "caption": {"type": "string", "description": "image layout: caption under the image"},
                                "notes": {"type": "string", "description": "speaker notes for this slide"},
                            },
                            "required": ["layout"],
                        },
                    },
                },
                "required": ["filename", "slides"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_xlsx",
            "description": (
                "Build a real Excel workbook (.xlsx) from structured data. ALWAYS prefer "
                "this over writing openpyxl code. Each sheet is {name, rows}; rows is an "
                "array of arrays — the FIRST row becomes the styled, frozen header. "
                "Numbers stay numeric. Saved in the project folder next to a "
                "<name>.preview.html grid viewer that opens automatically. Revise by "
                "calling again with the same filename."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "e.g. grades.xlsx"},
                    "title": {"type": "string", "description": "optional workbook title (metadata)"},
                    "sheets": {
                        "type": "array",
                        "description": "1-12 sheets, each {name, rows}",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "rows": {"type": "array", "items": {"type": "array"}, "description": "first row = header"},
                            },
                            "required": ["rows"],
                        },
                    },
                },
                "required": ["filename", "sheets"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_docx",
            "description": (
                "Build a real Word document (.docx) from a flat block list. ALWAYS prefer "
                "this over writing python-docx code. Blocks: {\"h1\"}, {\"h2\"}, {\"p\"}, "
                "{\"bullets\": [...]}, {\"numbers\": [...]}, {\"table\": {\"rows\": [[...]]}} "
                "(first row = header), {\"pagebreak\": true}. Saved in the project folder "
                "next to a <name>.preview.html page viewer that opens automatically. "
                "Revise by calling again with the same filename."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "e.g. essay.docx"},
                    "title": {"type": "string", "description": "document title (centered heading)"},
                    "blocks": {"type": "array", "description": "ordered content blocks", "items": {"type": "object"}},
                },
                "required": ["filename", "blocks"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_pdf",
            "description": (
                "Build a real PDF (A4) from the same flat block list as build_docx: "
                "{\"h1\"}, {\"h2\"}, {\"p\"}, {\"bullets\"}, {\"numbers\"}, "
                "{\"table\": {\"rows\": [[...]]}}, {\"pagebreak\": true}. Use for "
                "handouts, worksheets and print-ready school documents. Saved in the "
                "project folder next to a <name>.preview.html viewer that opens "
                "automatically. Revise by calling again with the same filename."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "e.g. worksheet.pdf"},
                    "title": {"type": "string", "description": "document title"},
                    "blocks": {"type": "array", "description": "ordered content blocks", "items": {"type": "object"}},
                },
                "required": ["filename", "blocks"],
            },
        },
    },
]


def format_ws_result(res):
    """One-line-ish human text for a workspace tool result dict."""
    if not res.get("ok"):
        return f"[denied/error: {res.get('error')}]"
    if "entries" in res:
        if not res["entries"]:
            return f"[{res['path'] or '.'}/ — empty]"
        lines = [f"[{(d['name'] + '/') if d['dir'] else d['name']}" + ("" if d["dir"] else f" ({d['size']}b)") + "]" for d in res["entries"]]
        return f"[{res['path'] or '.'}/]\n" + "\n".join(lines)
    if "content" in res:
        note = f" ({res['chars']} chars total, truncated)" if res.get("truncated") else f" ({res['chars']} chars)"
        return f"[{res['path']}{note}]\n{res['content']}"
    if "replaced" in res:
        return f"[edited {res['path']}: 1 anchor replaced]"
    if "exists" in res:
        return f"[folder {res['path']}" + (" — already existed]" if res["exists"] else " — created]")
    return f"[{res.get('path', 'ok')}: {res.get('chars', 0)} chars written]"


def format_pptx_result(res):
    """Human text for a build_pptx tool result."""
    if not res.get("ok"):
        return f"[pptx error: {res.get('error')}]"
    lines = [f"[pptx ok] {res['path']} · {res['slides']} slide(s) · theme {res['theme']} · preview: {res['preview']}"]
    lines += [f"[warn] {w}" for w in res.get("warnings", [])]
    return "\n".join(lines)


def format_doc_result(res, label):
    """Human text for a build_xlsx/docx/pdf tool result."""
    if not res.get("ok"):
        return f"[{label} error: {res.get('error')}]"
    summary = (
        f"{res['sheets']} sheet(s)" if "sheets" in res else f"{res['blocks']} block(s)"
    )
    lines = [f"[{label} ok] {res['path']} · {summary} · preview: {res['preview']}"]
    lines += [f"[warn] {w}" for w in res.get("warnings", [])]
    return "\n".join(lines)


def read_document_slice(conversation_id, arguments):
    """Return a slice of a stored document's text, addressed by its [doc N] label."""
    try:
        doc_num = int(arguments.get("doc"))
    except (TypeError, ValueError):
        return "[read_document: 'doc' must be the number from the [doc N] label]"
    offset = arguments.get("offset") or 0
    limit = arguments.get("limit") or INLINE_DOC_CHARS
    try:
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 20000))
    except (TypeError, ValueError):
        return "[read_document: offset/limit must be integers]"
    docs = [
        a for a in store.get_attachments_for_conversation(conversation_id)
        if a.get("kind") == "document"
    ]
    if doc_num < 1 or doc_num > len(docs):
        return f"[read_document: no document [doc {doc_num}] in this chat — available: 1..{len(docs)}]"
    ref = store.get_attachment(docs[doc_num - 1]["id"])
    text = (ref or {}).get("text") or ""
    if not text:
        return f"[read_document: [doc {doc_num}] has no extractable text]"
    chunk = text[offset:offset + limit]
    end = offset + len(chunk)
    header = f"[doc {doc_num} · {ref['filename']} · chars {offset}-{end} of {len(text)}]"
    if end < len(text):
        header += f"\n(more remains — call read_document again with offset={end})"
    return f"{header}\n{chunk}"


def build_history(rows):
    out = []
    for m in rows:
        entry = {"role": m["role"], "content": m["content"]}
        if m.get("tool_calls"):
            entry["tool_calls"] = m["tool_calls"]
        out.append(entry)
    return out


def accumulate_tool_calls(acc, incoming):
    for tc in incoming:
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        args = fn.get("arguments")
        if (
            acc
            and acc[-1]["name"] == name
            and isinstance(args, str)
            and isinstance(acc[-1]["args"], str)
        ):
            acc[-1]["args"] += args
        else:
            acc.append({"name": name, "args": args if isinstance(args, (str, dict)) else {}})
    return acc


def finalize_tool_call(entry):
    args = entry["args"]
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            args = {"code": args}
    if not isinstance(args, dict):
        args = {}
    return {"function": {"name": entry["name"], "arguments": args}}


def detect_content_tool_call(text):
    body = text.strip()
    if "<tool_call>" in body:
        body = body.replace("<tool_call>", "").replace("<" + "/tool_call>", "").strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if len(lines) >= 2:
            body = "\n".join(lines[1:-1]).strip()
    if not body.startswith("{"):
        return None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if isinstance(parsed.get("function"), dict):
        name = parsed["function"].get("name")
        raw_args = parsed["function"].get("arguments")
    else:
        name = parsed.get("name")
        raw_args = parsed.get("arguments")
    if name not in {t["function"]["name"] for t in TOOLS}:
        return None
    return {"name": name, "args": raw_args}


def tool_result_text(result):
    out = result["output"]
    if len(out) > MAX_RESULT_CHARS:
        out = out[:4000] + "\n...[output truncated]...\n" + out[-8000:]
    if result["timed_out"]:
        status = "killed: 30s timeout"
    elif result["capped"]:
        status = f"exit {result['exit']} — output truncated, process killed"
    else:
        status = f"exit {result['exit']}"
    if result.get("sandbox") == "unavailable":
        reason = result.get("sandbox_reason")
        status += " — sandbox: unavailable, ran unsandboxed"
        if reason:
            status += f" ({reason})"
    if not out.strip():
        return f"[no output — {status}]"
    return f"{out}\n[{status}]"


class ChatRequest(BaseModel):
    conversation_id: int
    content: str
    model: str = ""
    tools: bool = False
    think: bool | str | None = None
    code_mode: bool = False
    attachment_ids: list[int] = []


class AttachmentUpload(BaseModel):
    conversation_id: int
    filename: str = ""
    mime: str = ""
    data: str = ""


class AttachmentPathUpload(BaseModel):
    conversation_id: int
    path: str = ""
    filename: str = ""


class ClientLog(BaseModel):
    message: str = ""


class ConversationCreate(BaseModel):
    title: str = ""
    model: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    context_length: int = 0
    think: bool | str | None = None
    code_mode: bool = False


class ConversationUpdate(BaseModel):
    title: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    temperature: float | None = None
    context_length: int | None = None
    think: bool | str | None = None
    code_mode: bool | None = None


class SettingsUpdate(BaseModel):
    ollama_url: str | None = None
    accent: str | None = None
    show_stats: bool | None = None
    ide_open: bool | None = None
    ide_width: int | None = None
    sandbox_tools: bool | None = None
    sandbox_backend: str | None = None
    default_system_prompt: str | None = None
    default_system_prompt_casual: str | None = None
    default_temperature: float | None = None
    default_context_length: int | None = None
    default_think: bool | str | None = None
    loadout_casual_model: str | None = None
    loadout_code_model: str | None = None
    loadout_casual_ctx: int | None = None
    loadout_code_ctx: int | None = None
    bg_brightness: int | None = None
    bg_contrast: int | None = None
    loadout_casual_think: str | None = None
    settings_view: str | None = None
    engine: str | None = None
    engine_vulkan: bool | None = None
    workspace_root: str | None = None
    active_project: str | None = None


class RunRequest(BaseModel):
    code: str
    filename: str = "scratch.py"


class RunInput(BaseModel):
    run_id: str
    text: str


@app.get("/api/status")
async def status():
    return await ollama.server_status()


@app.get("/api/models")
async def models():
    return {"models": await ollama.list_models()}


ALLOWED_IMAGE_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}
# Extension -> mime, used when a file arrives by path (Wayland drop) with no
# browser-supplied content type.
IMAGE_EXT_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
# Documents whose extracted text is at or below this are inlined into the
# message; longer ones are stored and fetched on demand via read_document.
INLINE_DOC_CHARS = 8000


@app.get("/api/model/caps")
async def model_caps(model: str):
    """Capabilities the UI gates features on (vision -> show the [+] button)."""
    return {
        "tools": await ollama.model_supports_tools(model),
        "vision": await ollama.model_supports_vision(model),
    }


@app.post("/api/client-log")
async def client_log(body: ClientLog):
    """Frontend debug lines, printed to the backend terminal (kitty), so DnD
    diagnostics are visible without opening the webview devtools."""
    if os.environ.get("SU1RA_DEBUG") == "1":
        print(f"[su1ra:dnd] {body.message}", flush=True)
    return {"ok": True}


class PageInfoRequest(BaseModel):
    url: str = ""


@app.post("/api/page/info")
async def page_info(body: PageInfoRequest):
    """Probe a URL for the browser pane: frameable? fetchable? html or js?"""
    url = (body.url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "url must start with http:// or https://")
    return await asyncio.to_thread(documents.page_info, url)


class PageSummarizeRequest(BaseModel):
    conversation_id: int | None = None
    url: str = ""


@app.post("/api/page/summarize")
async def page_summarize(body: PageSummarizeRequest):
    """Fetch a page and return its extracted text so the chat can summarize it.

    The frontend injects the returned text as a user message; the model then
    summarizes it. Kept separate from /api/chat so the pane controls when.
    """
    url = (body.url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "url must start with http:// or https://")
    try:
        page = await asyncio.to_thread(documents.fetch_page_text, url)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))
    if page["js_rendered"]:
        raise HTTPException(
            502,
            "this page is JavaScript-rendered — its content isn't in the HTML, "
            "so it can't be summarized. Try [ open externally ].",
        )
    return page


def _store_attachment(conversation_id, filename, mime, data):
    """Validate + persist one uploaded file (image or document). Returns the ref."""
    mime = (mime or "").lower()
    filename = filename or ""
    ext = Path(filename).suffix.lower()
    # Files arriving by path (Wayland drop) carry no content type — infer it.
    if not mime and ext in IMAGE_EXT_MIME:
        mime = IMAGE_EXT_MIME[ext]
    is_image = mime in ALLOWED_IMAGE_MIME
    is_doc = documents.is_document_ext(ext) or mime in documents.DOCUMENT_MIMES
    if not is_image and not is_doc:
        raise HTTPException(415, f"unsupported file type: {mime or ext or 'unknown'}")
    if not store.get_conversation(conversation_id):
        raise HTTPException(404, "Conversation not found")
    if not data:
        raise HTTPException(422, "empty file")
    limit = MAX_IMAGE_BYTES if is_image else MAX_DOCUMENT_BYTES
    if len(data) > limit:
        raise HTTPException(413, f"file too large (max {limit // (1024 * 1024)} MB)")

    store.ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    if is_image:
        stored = store.ATTACHMENTS_DIR / f"{uuid.uuid4().hex}{ALLOWED_IMAGE_MIME[mime]}"
        stored.write_bytes(data)
        return store.add_attachment(
            conversation_id,
            filename=filename or stored.name,
            mime=mime,
            size=len(data),
            path=str(stored),
            kind="image",
        )

    # Document: keep the original file, extract its text once, store both.
    stored = store.ATTACHMENTS_DIR / f"{uuid.uuid4().hex}{ext or '.txt'}"
    stored.write_bytes(data)
    try:
        extracted = documents.extract(str(stored), filename or stored.name)
    except RuntimeError as exc:
        stored.unlink(missing_ok=True)
        raise HTTPException(422, str(exc))
    return store.add_attachment(
        conversation_id,
        filename=filename or stored.name,
        mime=mime or "application/octet-stream",
        size=len(data),
        path=str(stored),
        kind="document",
        text=extracted["text"],
        meta={**extracted.get("meta", {}), "doc_kind": extracted["kind"], "truncated": extracted["truncated"]},
    )


@app.post("/api/attachments")
async def upload_attachment(body: AttachmentUpload):
    """Accept a base64 image or document (JSON, no multipart dependency)."""
    try:
        data = base64.b64decode(body.data, validate=True)
    except Exception:
        raise HTTPException(422, "invalid base64 data")
    ref = _store_attachment(body.conversation_id, body.filename, body.mime, data)
    return {"attachment": ref}


@app.post("/api/attachments/from-path")
async def upload_attachment_from_path(body: AttachmentPathUpload):
    """Import a file by absolute path.

    Needed on Wayland/Hyprland, where a drag arrives as `text/uri-list` and the
    webview cannot read the dropped file itself — so the frontend sends the
    path and the backend reads it from disk.
    """
    raw = (body.path or "").strip()
    if raw.startswith("file://"):
        raw = raw[len("file://"):]
    try:
        raw = unquote(raw)
    except Exception:
        pass
    path = Path(raw)
    if not path.is_file():
        raise HTTPException(404, f"file not found: {path.name or raw}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise HTTPException(422, f"could not read file: {exc}")
    ref = _store_attachment(body.conversation_id, body.filename or path.name, "", data)
    return {"attachment": ref}


@app.get("/api/attachments/{attachment_id}")
async def get_attachment_file(attachment_id: int):
    ref = store.get_attachment(attachment_id)
    if not ref:
        raise HTTPException(404, "Attachment not found")
    path = Path(ref["path"])
    if not path.is_file():
        raise HTTPException(404, "Attachment file missing")
    return FileResponse(path, media_type=ref["mime"] or "application/octet-stream")


@app.get("/api/model/ctx")
async def model_ctx(model: str):
    return {"context_length": await ollama.model_context_length(model)}


@app.get("/api/disk")
async def disk():
    return {"free": await ollama.disk_free()}


@app.get("/api/ollama/state")
async def ollama_state():
    return {
        "binary": bool(ollama.find_binary()),
        "server": (await ollama.server_status())["ok"],
        "install_supported": ollama_setup.artifact_url() is not None,
    }


@app.post("/api/ollama/start")
async def ollama_start():
    return await ollama.ensure_running()


@app.post("/api/ollama/stop")
async def ollama_stop():
    """Stop the server only if Su1ra spawned it (never a user's own server)."""
    return {"ok": True, "stopped": ollama.stop_spawned()}


@app.get("/api/gpu")
async def gpu_info():
    """GPU discovery + the engine env a server restart would apply."""
    return {**ollama.detect_gpus(), "env": ollama.engine_env(), "spawned": ollama.has_spawned()}


@app.post("/api/ollama/restart")
async def ollama_restart():
    """Restart a Su1ra-spawned server so engine changes take effect.

    A server the user runs themselves is never touched: changing engine env
    requires restarting that server by hand (the /api/gpu env preview shows
    exactly which variables to set).
    """
    if (await ollama.server_status())["ok"] and not ollama.has_spawned():
        return {
            "ok": False,
            "error": "that server wasn't started by Su1ra — restart Ollama yourself for engine changes to apply",
        }
    ollama.stop_spawned()
    res = await ollama.ensure_running()
    if res.get("ok"):
        return {"ok": True, "started": True, "url": res.get("url")}
    return {"ok": False, "error": res.get("error", "could not start ollama")}


@app.post("/api/ollama/install")
async def ollama_install():
    async def stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def send(obj):
            await queue.put(obj)

        async def run():
            try:
                await ollama_setup.install(send)
            finally:
                await queue.put({"__done": True})

        task = asyncio.create_task(run())
        try:
            while True:
                evt = await queue.get()
                if evt.get("__done"):
                    break
                yield json.dumps(evt) + "\n"
        finally:
            task.cancel()

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class PullRequest(BaseModel):
    model: str


@app.post("/api/models/pull")
async def pull_model(body: PullRequest):
    name = body.model.strip()
    if not name:
        raise HTTPException(422, "model name required")

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def send(obj):
            await queue.put(obj)

        async def run():
            try:
                await puller.pull(name, send)
            finally:
                await queue.put({"__done": True})

        task = asyncio.create_task(run())
        try:
            while True:
                evt = await queue.get()
                if evt.get("__done"):
                    break
                yield json.dumps(evt) + "\n"
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post("/api/models/pull/cancel")
async def cancel_pull(body: PullRequest):
    puller.cancel(body.model.strip())
    return {"ok": True}


@app.post("/api/models/unload")
async def unload_model(body: PullRequest):
    """Unload a model from the Ollama server to free memory.

    Best-effort: returns ok True only when the server accepted the unload.
    Callers switch modes regardless — a failed unload just leaves the old
    model warm until Ollama evicts it.
    """
    name = body.model.strip()
    if not name:
        raise HTTPException(422, "model name required")
    return {"ok": True, "unloaded": await ollama.unload_model(name)}


@app.delete("/api/models/{name:path}")
async def delete_model(name: str):
    name = name.strip()
    if not name:
        raise HTTPException(422, "model name required")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request("DELETE", f"{ollama.base_url()}/api/delete", json={"model": name})
    except Exception as exc:
        raise HTTPException(502, f"cannot reach ollama server: {exc}")
    if resp.status_code == 404:
        raise HTTPException(404, f'model "{name}" not found')
    if resp.status_code != 200:
        raise HTTPException(502, f"ollama refused: {resp.text[:200]}")
    return {"ok": True, "deleted": name}


@app.get("/api/settings")
async def get_settings():
    return {
        "ollama_url": store.get_setting("ollama_url") or ollama.DEFAULT_URL,
        "accent": store.get_setting("accent") or "#bf264a",
        "show_stats": store.get_setting("show_stats") == "1",
        "ide_open": store.get_setting("ide_open") == "1",
        "ide_width": int(store.get_setting("ide_width") or 460),
        "sandbox_tools": store.get_setting("sandbox_tools") != "0",
        "sandbox_backend": store.get_setting("sandbox_backend") or "auto",
        "default_system_prompt": store.get_setting("default_system_prompt") or "",
        "default_system_prompt_casual": store.get_setting("default_system_prompt_casual") or "",
        "default_temperature": float(store.get_setting("default_temperature") or 0.7),
        "default_context_length": int(store.get_setting("default_context_length") or 0),
        "default_think": store.get_setting("default_think") or None,
        "loadout_casual_model": store.get_setting("loadout_casual_model") or "",
        "loadout_code_model": store.get_setting("loadout_code_model") or "",
        "loadout_casual_ctx": int(store.get_setting("loadout_casual_ctx") or 0),
        "loadout_code_ctx": int(store.get_setting("loadout_code_ctx") or 0),
        "bg_brightness": int(store.get_setting("bg_brightness") or 100),
        "bg_contrast": int(store.get_setting("bg_contrast") or 100),
        "loadout_casual_think": store.get_setting("loadout_casual_think") or "",
        "settings_view": store.get_setting("settings_view") or "split",
        "engine": store.get_setting("engine") or "auto",
        "engine_vulkan": store.get_setting("engine_vulkan") == "1",
        "workspace_root": str(workspace.root()),
        "active_project": workspace.active_project(),
    }


@app.patch("/api/settings")
async def update_settings(body: SettingsUpdate):
    if (
        body.ollama_url is None
        and body.accent is None
        and body.show_stats is None
        and body.ide_open is None
        and body.ide_width is None
        and body.sandbox_tools is None
        and body.sandbox_backend is None
        and body.default_system_prompt is None
        and body.default_temperature is None
        and body.default_context_length is None
        and body.default_think is None
        and body.loadout_casual_model is None
        and body.loadout_code_model is None
        and body.loadout_casual_ctx is None
        and body.loadout_code_ctx is None
        and body.bg_brightness is None
        and body.bg_contrast is None
        and body.loadout_casual_think is None
        and body.settings_view is None
        and body.engine is None
        and body.engine_vulkan is None
        and body.workspace_root is None
        and body.active_project is None
    ):
        raise HTTPException(422, "nothing to update")
    if body.default_think is not None:
        try:
            think = store.normalize_think(body.default_think)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if think is None:
            store.set_setting("default_think", "")
        else:
            store.set_setting("default_think", think)
    if body.default_system_prompt is not None:
        store.set_setting("default_system_prompt", body.default_system_prompt)
    if body.default_system_prompt_casual is not None:
        store.set_setting("default_system_prompt_casual", body.default_system_prompt_casual)
    if body.default_temperature is not None:
        store.set_setting("default_temperature", str(body.default_temperature))
    if body.default_context_length is not None:
        store.set_setting("default_context_length", str(max(0, int(body.default_context_length))))
    if body.loadout_casual_model is not None:
        store.set_setting("loadout_casual_model", body.loadout_casual_model.strip())
    if body.loadout_code_model is not None:
        store.set_setting("loadout_code_model", body.loadout_code_model.strip())
    if body.loadout_casual_ctx is not None:
        store.set_setting("loadout_casual_ctx", str(max(0, int(body.loadout_casual_ctx))))
    if body.loadout_code_ctx is not None:
        store.set_setting("loadout_code_ctx", str(max(0, int(body.loadout_code_ctx))))
    if body.bg_brightness is not None:
        store.set_setting("bg_brightness", str(max(0, min(150, int(body.bg_brightness)))))
    if body.bg_contrast is not None:
        store.set_setting("bg_contrast", str(max(0, min(150, int(body.bg_contrast)))))
    if body.loadout_casual_think is not None:
        v = body.loadout_casual_think.strip().lower()
        if v not in ("on", "off", ""):
            raise HTTPException(422, "loadout_casual_think must be on, off, or empty")
        store.set_setting("loadout_casual_think", v)
    if body.settings_view is not None:
        v = body.settings_view.strip().lower()
        if v not in ("list", "split"):
            raise HTTPException(422, "settings_view must be list or split")
        store.set_setting("settings_view", v)
    if body.engine is not None:
        v = body.engine.strip().lower()
        if v not in ("auto", "cpu", "gpu"):
            raise HTTPException(422, "engine must be auto, cpu, or gpu")
        store.set_setting("engine", v)
    if body.engine_vulkan is not None:
        store.set_setting("engine_vulkan", "1" if body.engine_vulkan else "0")
    if body.ollama_url is not None:
        if not body.ollama_url.startswith(("http://", "https://")):
            raise HTTPException(422, "ollama_url must start with http:// or https://")
        store.set_setting("ollama_url", body.ollama_url.rstrip("/"))
    if body.accent is not None:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", body.accent):
            raise HTTPException(422, "accent must be a hex color like #bf264a")
        store.set_setting("accent", body.accent.lower())
    if body.show_stats is not None:
        store.set_setting("show_stats", "1" if body.show_stats else "0")
    if body.ide_open is not None:
        store.set_setting("ide_open", "1" if body.ide_open else "0")
    if body.sandbox_tools is not None:
        store.set_setting("sandbox_tools", "1" if body.sandbox_tools else "0")
    if body.sandbox_backend is not None:
        v = body.sandbox_backend.strip().lower()
        if v not in ("auto", "wsl", "off"):
            raise HTTPException(422, "sandbox_backend must be auto, wsl, or off")
        store.set_setting("sandbox_backend", v)
    if body.ide_width is not None:
        if not 280 <= body.ide_width <= 1200:
            raise HTTPException(422, "ide_width must be between 280 and 1200")
        store.set_setting("ide_width", str(body.ide_width))
    if body.workspace_root is not None:
        try:
            store.set_setting("workspace_root", workspace.validate_root(body.workspace_root))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    if body.active_project is not None:
        if body.active_project.strip() == "":
            store.set_setting("active_project", "")
        else:
            try:
                workspace.set_active_project(body.active_project)
            except ValueError as exc:
                raise HTTPException(422, str(exc))
    return {
        "ok": True,
        "ollama_url": store.get_setting("ollama_url") or ollama.DEFAULT_URL,
        "accent": store.get_setting("accent") or "#bf264a",
        "show_stats": store.get_setting("show_stats") == "1",
        "ide_open": store.get_setting("ide_open") == "1",
        "ide_width": int(store.get_setting("ide_width") or 460),
        "sandbox_tools": store.get_setting("sandbox_tools") != "0",
    }


@app.get("/api/system-prompt/bundled")
async def system_prompt_bundled():
    return {"content": store.bundled_system_prompt()}


@app.get("/api/system-prompt/file")
async def system_prompt_file():
    if not store.PROMPT_FILE.exists():
        return {"content": None, "mtime": None}
    return {
        "content": store.PROMPT_FILE.read_text(encoding="utf-8"),
        "mtime": store.PROMPT_FILE.stat().st_mtime,
    }


class SystemPromptOpen(BaseModel):
    content: str = ""


@app.post("/api/system-prompt/open")
async def system_prompt_open(body: SystemPromptOpen):
    """Write the draft to the user's prompt file and open it in the OS
    default .txt editor (the user's own choice). The frontend polls
    /api/system-prompt/file and picks up saves."""
    store.PROMPT_FILE.write_text(body.content, encoding="utf-8")
    try:
        if os.name == "nt":
            os.startfile(str(store.PROMPT_FILE))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(store.PROMPT_FILE)])
        else:
            subprocess.Popen(["xdg-open", str(store.PROMPT_FILE)])
    except Exception as exc:
        raise HTTPException(502, f"could not open a text editor: {exc}")
    return {"ok": True, "path": str(store.PROMPT_FILE), "mtime": store.PROMPT_FILE.stat().st_mtime}


@app.post("/api/eject")
async def eject():
    # taskkill targets the launcher, but orphaned llama-server.exe workers
    # (parent already gone) survive it — kill them by name too, or memory
    # stays occupied after eject.
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/IM", "ollama.exe"], capture_output=True)
        subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "ollama serve"], capture_output=True)
        subprocess.run(["pkill", "-f", "llama-server"], capture_output=True)
    for _ in range(10):
        if not (await ollama.server_status())["ok"]:
            break
        await asyncio.sleep(0.2)
    else:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/IM", "ollama.exe"], capture_output=True)
            subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], capture_output=True)
        else:
            subprocess.run(["pkill", "-9", "-f", "ollama serve"], capture_output=True)
            subprocess.run(["pkill", "-9", "-f", "llama-server"], capture_output=True)
        await asyncio.sleep(0.3)
    return {"ok": True, "server_ok": (await ollama.server_status())["ok"]}


@app.post("/api/connect")
async def connect():
    return await ollama.ensure_running()


@app.get("/api/conversations")
async def conversations():
    return {"conversations": store.list_conversations()}


@app.post("/api/conversations")
async def create_conversation(body: ConversationCreate):
    try:
        think = store.normalize_think(body.think)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return store.create_conversation(
        body.title, body.model, body.system_prompt, body.temperature, body.context_length, think,
        code_mode=body.code_mode,
    )


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: int):
    conversation = store.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return {"conversation": conversation, "messages": store.get_messages(conversation_id)}


@app.patch("/api/conversations/{conversation_id}")
async def update_conversation(conversation_id: int, body: ConversationUpdate):
    kwargs = dict(
        title=body.title,
        model=body.model,
        system_prompt=body.system_prompt,
        temperature=body.temperature,
        context_length=body.context_length,
        code_mode=body.code_mode,
    )
    if body.think is not None:
        try:
            kwargs["think"] = store.normalize_think(body.think)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    try:
        updated = store.update_conversation(conversation_id, **kwargs)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not updated:
        raise HTTPException(404, "Conversation not found")
    return updated


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int):
    if not store.delete_conversation(conversation_id):
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}


@app.post("/api/conversations/clear-all")
async def clear_all_conversations():
    count = store.delete_all_conversations()
    return {"ok": True, "deleted": count}


@app.post("/api/conversations/{conversation_id}/clear")
async def clear_conversation(conversation_id: int):
    if not store.get_conversation(conversation_id):
        raise HTTPException(404, "Conversation not found")
    count = store.clear_conversation_messages(conversation_id)
    return {"ok": True, "cleared": count}


class PreviewBody(BaseModel):
    path: str


@app.post("/api/preview")
async def preview_file(body: PreviewBody):
    """Generate <name>.preview.html for an existing pptx/xlsx/docx/pdf/svg in
    the active project (or workspace root). Read-only for the source file."""
    if not body.path.strip():
        raise HTTPException(422, "path required")
    try:
        target = workspace.resolve(body.path)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not target.is_file():
        raise HTTPException(404, f"no such file: {body.path}")
    try:
        res = doc_builders.preview_existing(target)
    except doc_builders.OutlineError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"preview failed: {exc}")
    return {"ok": True, "path": res["path"], "source": res["source"]}


@app.post("/api/chat")
async def chat(body: ChatRequest):
    conversation = store.get_conversation(body.conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    content = body.content.strip()
    if not content and not body.attachment_ids:
        raise HTTPException(422, "Empty message")
    model = body.model or conversation["model"]
    if not model:
        raise HTTPException(422, "No model selected")

    # Resolve picked attachments first. Images are base64'd for Ollama and
    # labelled [image N]; documents are labelled [doc N] and either inlined
    # (short) or left for the read_document tool (long). Labels are
    # per-conversation (1..n per kind), assigned in the order sent, so the
    # model can map prose references ("this [image 1]", "in [doc 2]") to a
    # specific attachment.
    image_b64 = []
    image_labels = []
    doc_labels = []
    inline_docs = []
    deferred_docs = []
    for aid in body.attachment_ids:
        ref = store.get_attachment(aid)
        # Only label attachments that are actually pending in this conversation
        # — the same set attach_to_message will link — so labels and stored idx
        # can never drift apart.
        if not ref or ref["conversation_id"] != body.conversation_id or ref["message_id"] is not None:
            continue
        if ref.get("kind") == "document":
            n = len(doc_labels) + 1
            doc_labels.append(f"[doc {n}]")
            text = ref.get("text") or ""
            if text and len(text) <= INLINE_DOC_CHARS:
                inline_docs.append((n, ref["filename"], text))
            else:
                deferred_docs.append((n, ref["filename"], len(text)))
            continue
        try:
            raw = Path(ref["path"]).read_bytes()
        except OSError:
            continue
        image_b64.append(base64.b64encode(raw).decode("ascii"))
        image_labels.append(f"[image {len(image_labels) + 1}]")

    prefix = " ".join(image_labels + doc_labels)
    if prefix:
        content = f"{prefix}\n{content}".strip()
    for n, name, text in inline_docs:
        content += f"\n\n--- [doc {n}] {name} ---\n{text}"
    for n, name, length in deferred_docs:
        content += (
            f"\n\n--- [doc {n}] {name} ---\n"
            f"(long document, {length} chars — use the read_document tool with doc={n} to read it)"
        )

    user_row = store.add_message(body.conversation_id, "user", content)
    if not conversation["title"]:
        store.update_conversation(body.conversation_id, title=content[:60])
    if body.attachment_ids:
        store.attach_to_message(body.attachment_ids, user_row["id"], body.conversation_id)
    history = build_history(store.get_messages(body.conversation_id))
    if image_b64 and history:
        history[-1]["images"] = image_b64
    # Tools are strictly code-mode: casual never offers them, no matter what
    # the client asked for. (The old ```python auto-arm is gone on purpose.)
    tools = TOOLS if body.tools and body.code_mode and await ollama.model_supports_tools(model) else None
    think = body.think if body.think is not None else conversation.get("think")
    # The stored system prompt only applies in code mode — casual chats
    # go out with no system prompt.
    # System prompts are per-mode: build carries the bundled sysp.txt default
    # (settings key default_system_prompt), casual carries its own default
    # (default_system_prompt_casual — empty out of the box). A non-empty
    # per-chat override wins in either mode.
    per_chat = (conversation["system_prompt"] or "").strip()
    if body.code_mode:
        sys_prompt = per_chat or (store.get_setting("default_system_prompt") or "")
    else:
        sys_prompt = per_chat or (store.get_setting("default_system_prompt_casual") or "")
    if tools:
        ws_rules = (
            f"Workspace: ROOT={workspace.root()} PROJECT={workspace.project_dir()}. "
            "File tools (ws_ls/read/write/edit/mkdir) resolve inside ROOT only — "
            "paths relative to PROJECT, never absolute. "
            "NEW PROJECTS: before producing files for a new project, ALWAYS make a fresh "
            "folder and enter it in one step with ws_cd (it creates the folder if missing) "
            "— pick a short kebab-case name from the request, e.g. ws_cd photosynthesis-deck. "
            "NEVER write files straight into the workspace root or reuse the current "
            "project for a different task; only work in an existing project when the user "
            "clearly means it (\"fix my deck\", \"continue the essay\"). "
            "Read a file before editing it; "
            "ws_edit needs an anchor matching exactly once (check the match count). "
            "One edit per call. Never paste file contents into chat — confirm in one line. "
            "If a tool says denied, stop and ask the user in plain words; never retry paths. "
            "Artifacts you build live as files in PROJECT (single-file HTML runs as saved); "
            "mention the file path instead of re-emitting content. "
            "When the user asks about files, directories, or project contents, you MUST "
            "call ws_ls/ws_read first — answering from memory or refusing without calling "
            "is a failure. Greetings need no tools."
        )
        directive = (
            "You have file tools plus run_python. Use them proactively for computation, "
            "running code, and file work — call them instead of guessing results. "
            "For slide decks (.pptx), call the build_pptx tool with a structured outline "
            "instead of writing python-pptx code — it saves the deck plus an HTML slide "
            "preview that opens automatically in the preview pane. Same for other school "
            "formats: build_xlsx (Excel workbooks), build_docx (Word documents) and "
            "build_pdf (PDF handouts/worksheets) all take a structured outline and save "
            "the file plus an auto-opening preview. " + ws_rules
        )
        sys_prompt = f"{sys_prompt}\n\n{directive}" if sys_prompt.strip() else directive
        # Auto-context (always): the model sees the live project listing every
        # code-mode turn, so "I can't see your files" refusals contradict
        # visible context. Best-effort and silent — a failure here must never
        # break the turn.
        try:
            if workspace.active_project():
                ls_res = workspace.ls("")
                if ls_res.get("ok"):
                    entries = ls_res["entries"][:60]
                    lines = [
                        (e["name"] + "/") if e["dir"] else f"{e['name']} ({e['size']}b)"
                        for e in entries
                    ]
                    if len(ls_res["entries"]) > 60:
                        lines.append(f"...(+{len(ls_res['entries']) - 60} more — ws_ls to see all)")
                    listing = "\n".join(lines) if lines else "(empty project — ws_write to create files)"
                    sys_prompt += (
                        f"\n\n[project {workspace.active_project()} contents — "
                        "you CAN read these with ws_read]\n" + listing
                    )
            else:
                sys_prompt += (
                    "\n\n[no active project — if the user wants file work, do NOT ask them "
                    "to run commands: pick a short folder name for the project and call "
                    "ws_cd <name> (it creates the folder and switches to it), then work]"
                )
        except Exception:
            pass

    async def generator():
        yield json.dumps({"user_id": user_row["id"]}) + "\n"
        working = list(history)

        for round_idx in range(MAX_TOOL_ROUNDS + 1):
            with_tools = round_idx < MAX_TOOL_ROUNDS
            text = ""
            stats = None
            pending_calls = []
            saved = False
            saved_id = None
            consumed = False

            def save():
                nonlocal saved, saved_id
                if saved or (not text.strip() and not pending_calls):
                    return
                saved_id = store.add_message(
                    body.conversation_id,
                    "assistant",
                    "" if consumed else text.strip(),
                    stats,
                    tool_calls=[finalize_tool_call(tc) for tc in pending_calls] if pending_calls else None,
                )["id"]
                saved = True

            try:
                async for chunk in ollama.stream_chat(
                    model,
                    working,
                    sys_prompt,
                    conversation["temperature"],
                    conversation["context_length"],
                    tools=tools if with_tools else None,
                    think=think,
                ):
                    if "error" in chunk:
                        save()
                        yield json.dumps(chunk) + "\n"
                        return
                    if "tool_calls" in chunk:
                        accumulate_tool_calls(pending_calls, chunk["tool_calls"])
                        continue
                    if "stats" in chunk:
                        stats = chunk["stats"]
                    if "done" in chunk:
                        continue
                    if "delta" in chunk:
                        text += chunk["delta"]
                    yield json.dumps(chunk) + "\n"
                if with_tools and tools and not pending_calls:
                    detected = detect_content_tool_call(text)
                    if detected:
                        pending_calls.append(detected)
                        consumed = True
            finally:
                save()

            if not pending_calls:
                eval_count = stats["eval_count"] if stats else 0
                yield json.dumps({"done": True, "eval_count": eval_count, "assistant_id": saved_id}) + "\n"
                return

            finalized = [finalize_tool_call(tc) for tc in pending_calls]
            working.append({"role": "assistant", "content": "" if consumed else text.strip(), "tool_calls": finalized})
            for call in finalized:
                name = call["function"]["name"]
                arguments = call["function"]["arguments"]
                if not isinstance(arguments, dict):
                    arguments = {}
                code = str(arguments.get("code") or "") if name == "run_python" else ""
                ws_path = str(arguments.get("path") or "")
                # Defaults first: no dispatch branch may leave these unbound
                # (a missing assignment used to raise UnboundLocalError after
                # tool_start and silently kill the stream), and a later tool
                # call must never reuse the previous call's result text.
                result = None
                result_text = f"[internal error: tool '{name}' produced no result — tell the user and continue]"
                yield json.dumps({"tool_start": {"name": name}}) + "\n"
                if name == "run_python":
                    try:
                        result = await runner.run_python(
                            code,
                            sandboxed=store.get_setting("sandbox_tools") != "0",
                            cwd=str(workspace.project_dir()),
                            backend=store.get_setting("sandbox_backend") or "auto",
                        )
                        result_text = tool_result_text(result)
                    except Exception as exc:
                        result = None
                        result_text = f"[execution error: {exc}]"
                elif name in ("ws_ls", "ws_read", "ws_write", "ws_edit", "ws_mkdir", "ws_cd"):
                    try:
                        if name == "ws_ls":
                            ws_res = workspace.ls(ws_path)
                        elif name == "ws_read":
                            ws_res = workspace.read(ws_path)
                        elif name == "ws_write":
                            ws_res = workspace.write(ws_path, arguments.get("content") or "")
                        elif name == "ws_edit":
                            ws_res = workspace.edit(ws_path, arguments.get("find") or "", arguments.get("replacement") or "")
                        elif name == "ws_cd":
                            # mkdir-if-missing + switch, atomically: starting a
                            # new project is always "new folder, then enter it".
                            target = str(arguments.get("project") or arguments.get("path") or "").strip()
                            if not target:
                                ws_res = {"ok": False, "error": "name the project folder to cd into"}
                            else:
                                made = workspace.mkdir(target)
                                if not made.get("ok"):
                                    ws_res = made
                                else:
                                    shown = workspace.set_active_project(target)
                                    ws_res = {"ok": True, "path": shown, "created": not made.get("exists", True)}
                            result = {"exit": 0 if ws_res.get("ok") else 1, "ws": ws_res}
                            result_text = (
                                f"[project: {ws_res['path']}"
                                + (" — created]" if ws_res.get("created") else "]")
                                if ws_res.get("ok")
                                else f"[denied/error: {ws_res.get('error')}]"
                            )
                        else:
                            ws_res = workspace.mkdir(ws_path)
                        if name != "ws_cd":
                            result = {"exit": 0 if ws_res.get("ok") else 1, "ws": ws_res}
                            result_text = format_ws_result(ws_res)
                        if name in ("ws_cd", "ws_mkdir"):
                            # refresh the header/auto-context project info
                            ws_path = ""
                    except Exception as exc:
                        result = None
                        result_text = f"[workspace error: {exc}]"
                elif name == "build_pptx":
                    args = dict(arguments)
                    if "slides" not in args and args.get("code"):
                        # finalize_tool_call parks unparseable-JSON args under
                        # "code" (its run_python fallback) — recover the real
                        # outline from that string before giving up.
                        try:
                            recovered = json.loads(str(args["code"]))
                            if isinstance(recovered, dict):
                                args = recovered
                        except (json.JSONDecodeError, TypeError):
                            pass
                    try:
                        res = pptx_builder.build_deck(args, workspace.project_dir())
                        result = {"exit": 0, "ws": res}
                        result_text = format_pptx_result(res)
                        # The preview player is plain html — reuse the artifact
                        # pane bridge by reporting it as the event path.
                        ws_path = res["preview"]
                    except pptx_builder.OutlineError as exc:
                        result = {"exit": 1, "ws": {"ok": False, "error": str(exc)}}
                        result_text = f"[pptx outline rejected: {exc}]"
                    except Exception as exc:
                        result = None
                        result_text = f"[pptx error: {exc}]"
                elif name in ("build_xlsx", "build_docx", "build_pdf"):
                    args = dict(arguments)
                    body_keys = ("sheets", "blocks", "rows") if name == "build_xlsx" else ("blocks",)
                    if not any(k in args for k in body_keys) and args.get("code"):
                        # finalize_tool_call parks unparseable-JSON args under
                        # "code" (its run_python fallback) — recover first.
                        try:
                            recovered = json.loads(str(args["code"]))
                            if isinstance(recovered, dict):
                                args = recovered
                        except (json.JSONDecodeError, TypeError):
                            pass
                    try:
                        if name == "build_xlsx":
                            res = doc_builders.build_xlsx(args, workspace.project_dir())
                        elif name == "build_docx":
                            res = doc_builders.build_docx(args, workspace.project_dir())
                        else:
                            res = doc_builders.build_pdf(args, workspace.project_dir())
                        result = {"exit": 0, "ws": res}
                        result_text = format_doc_result(res, name.replace("build_", ""))
                        ws_path = res["preview"]
                    except doc_builders.OutlineError as exc:
                        result = {"exit": 1, "ws": {"ok": False, "error": str(exc)}}
                        result_text = f"[{name} outline rejected: {exc}]"
                    except Exception as exc:
                        result = None
                        result_text = f"[{name} error: {exc}]"
                elif name == "read_document":
                    result = None
                    result_text = read_document_slice(body.conversation_id, arguments)
                else:
                    result = None
                    result_text = f"Unknown tool: {name}. Available: run_python, ws_ls, ws_read, ws_write, ws_edit, ws_mkdir, ws_cd, build_pptx, build_xlsx, build_docx, build_pdf, read_document."
                row = store.add_message(body.conversation_id, "tool", result_text)
                working.append({"role": "tool", "content": result_text})
                yield json.dumps(
                    {
                        "tool": {
                            "name": name,
                            "code": code,
                            "path": ws_path if (name.startswith("ws_") or name.startswith("build_")) else "",
                            "output": result_text,
                            "id": row["id"],
                            "exit": result["exit"] if result else None,
                            "replaces_text": consumed,
                        }
                    }
                ) + "\n"

    return StreamingResponse(generator(), media_type="application/x-ndjson")


@app.delete("/api/messages/{message_id}/following")
async def delete_message_following(message_id: int):
    """Delete a message and everything after it (edit/regenerate truncation)."""
    if not store.delete_message_and_following(message_id):
        raise HTTPException(404, "Message not found")
    return {"ok": True}


@app.post("/api/run")
async def run(body: RunRequest):
    run_id = uuid.uuid4().hex
    if not body.code.strip():
        raise HTTPException(422, "Empty code")
    # subpath-aware ('proj/main.py'); traversal-safe; cwd = the file's parent
    target = _editor_rel_path(body.filename)
    argv, env_over = build_run_argv(target.name)
    if argv is None:
        raise HTTPException(422, env_over)
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.parent
    # Save the buffer to a REAL file first — runs respect the file type and
    # get __file__ / sibling imports / shebangs, like a text editor would.
    target.write_text(body.code, encoding="utf-8", newline="\n")
    if HAS_PTY:
        return StreamingResponse(pty_generator(run_id, argv, scratch, env_over), media_type="application/x-ndjson")

    async def legacy_generator():
        proc = None

        def kill_proc():
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except Exception:
                    pass

        try:
            yield json.dumps({"run": run_id}) + "\n"
            proc = await asyncio.create_subprocess_exec(
                argv[0],
                *argv[1:],
                cwd=scratch,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **env_over},
                **runner.child_spawn_kwargs(),
            )
            RUN_STDIN[run_id] = proc.stdin
            queue = asyncio.Queue()

            async def read_stream(stream, name):
                buf = b""
                while True:
                    chunk = await stream.read(8192)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        await queue.put((name, line.decode("utf-8", errors="replace")))
                if buf:
                    await queue.put((name, buf.decode("utf-8", errors="replace")))
                await queue.put((name, None))

            readers = [
                asyncio.create_task(read_stream(proc.stdout, "stdout")),
                asyncio.create_task(read_stream(proc.stderr, "stderr")),
            ]
            deadline = asyncio.get_running_loop().time() + 30
            done = 0
            lines = 0
            total_bytes = 0
            capped = False
            try:
                while done < 2:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        kill_proc()
                        await proc.wait()
                        yield json.dumps({"stream": "stderr", "line": "// timeout — killed after 30s"}) + "\n"
                        yield json.dumps({"exit": -1}) + "\n"
                        return
                    try:
                        name, line = await asyncio.wait_for(queue.get(), timeout=remaining)
                    except asyncio.TimeoutError:
                        kill_proc()
                        await proc.wait()
                        yield json.dumps({"stream": "stderr", "line": "// timeout — killed after 30s"}) + "\n"
                        yield json.dumps({"exit": -1}) + "\n"
                        return
                    if line is None:
                        done += 1
                        continue
                    lines += 1
                    total_bytes += len(line.encode("utf-8"))
                    if lines > 2000 or total_bytes > 1024 * 1024:
                        capped = True
                        break
                    yield json.dumps({"stream": name, "line": line}) + "\n"
            finally:
                for task in readers:
                    task.cancel()
            if capped:
                kill_proc()
                await proc.wait()
                yield json.dumps({"stream": "stderr", "line": "// output truncated — process killed"}) + "\n"
                yield json.dumps({"exit": -1}) + "\n"
                return
            returncode = await proc.wait()
            yield json.dumps({"exit": returncode}) + "\n"
        except FileNotFoundError as e:
            yield json.dumps({"error": str(e)}) + "\n"
        except Exception as e:
            yield json.dumps({"error": str(e)}) + "\n"
        finally:
            RUN_STDIN.pop(run_id, None)
            try:
                if proc is not None and proc.stdin is not None and not proc.stdin.is_closing():
                    proc.stdin.close()
            except Exception:
                pass
            kill_proc()

    return StreamingResponse(legacy_generator(), media_type="application/x-ndjson")


def term_note(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


async def pty_generator(run_id, argv, scratch, env_over):
    sess = ptyrunner.PtySession(argv, scratch, env_over)
    try:
        sess.start()
    except Exception as exc:
        yield json.dumps({"error": str(exc)}) + "\n"
        return
    RUN_PTY[run_id] = sess
    try:
        yield json.dumps({"run": run_id, "term": True}) + "\n"
        start = time.monotonic()
        total = 0
        while True:
            chunk = await asyncio.to_thread(sess.read, 0.25)
            if chunk:
                total += len(chunk)
                if total > TERM_OUTPUT_CAP:
                    sess.kill()
                    yield json.dumps({"o": term_note("\r\n// output cap reached — process killed\r\n")}) + "\n"
                    yield json.dumps({"exit": -9}) + "\n"
                    return
                yield json.dumps({"o": base64.b64encode(chunk).decode("ascii")}) + "\n"
            if chunk is None or chunk == b"":
                rc = sess.poll()
                if chunk == b"" or rc is not None:
                    break
            now = time.monotonic()
            if sess.stop_deadline is not None and now > sess.stop_deadline and sess.alive():
                sess.kill()
            if now - start > TIMEOUT_SECONDS and sess.alive():
                sess.kill()
                yield json.dumps({"o": term_note("\r\n// timeout — killed after 30s\r\n")}) + "\n"
                yield json.dumps({"exit": -9}) + "\n"
                return
        rc = sess.poll()
        if rc is None:
            sess.close()
            rc = sess.poll()
        yield json.dumps({"exit": rc if rc is not None else -1}) + "\n"
    except asyncio.CancelledError:
        sess.close()
        raise
    except Exception as exc:
        yield json.dumps({"error": str(exc)}) + "\n"
    finally:
        RUN_PTY.pop(run_id, None)
        sess.close()


@app.post("/api/run/input")
async def run_input(body: RunInput):
    sess = RUN_PTY.get(body.run_id)
    if sess is not None:
        if not sess.write(body.text):
            raise HTTPException(409, "Cannot write to terminal")
        if "\x03" in body.text:
            sess.stop_deadline = time.monotonic() + 2.5
        return {"ok": True}
    writer = RUN_STDIN.get(body.run_id)
    if writer is None:
        raise HTTPException(404, "No running process for that run id")
    try:
        writer.write((body.text + "\n").encode("utf-8"))
        await writer.drain()
    except Exception as exc:
        raise HTTPException(409, f"Cannot write to stdin: {exc}")
    return {"ok": True}


class EditorFileBody(BaseModel):
    code: str
    filename: str = "scratch.py"


# --- editor scratch root -----------------------------------------------------
# The editor's files live in ~/Documents/.scratch — user-visible, app-folder
# vibes (dot-prefixed). Sub-folders are allowed (user-made); every path goes
# through _editor_rel_path which rejects traversal and resolves inside the
# root. The legacy flat %APPDATA% scratch dir migrates once, by copy.

def editor_root():
    docs = Path.home() / "Documents"
    root = docs / ".scratch"
    _migrate_legacy_scratch(root)
    return root


def _migrate_legacy_scratch(root):
    if getattr(editor_root, "_migrated", False) or root.exists():
        editor_root._migrated = True
        return
    legacy = store.DATA_DIR / "scratch"
    if legacy.is_dir():
        root.mkdir(parents=True, exist_ok=True)
        for f in legacy.iterdir():
            if f.is_file():
                shutil.copy2(f, root / f.name)
    editor_root._migrated = True


def _editor_rel_path(filename):
    """Validate a slash-separated relative path ('a/b.py'); returns the
    resolved absolute path INSIDE the editor root or raises HTTPException."""
    filename = (filename or "").strip().replace("\\", "/").lstrip("/")
    if not filename:
        raise HTTPException(422, "Empty filename")
    for part in filename.split("/"):
        if part in ("", ".", ".."):
            raise HTTPException(422, f"Bad path segment: {part!r}")
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,80}$", part):
            raise HTTPException(422, f"Bad filename: {part!r}")
    target = (editor_root() / filename).resolve()
    root = editor_root().resolve()
    if target != root and root not in target.parents:
        raise HTTPException(422, "Path escapes the scratch folder")
    return target


_EDITOR_OPEN_CAP = 400_000  # chars — refuse to open monsters into the buffer


@app.post("/api/editor/file")
async def save_editor_file(body: EditorFileBody):
    """Save an editor buffer into the scratch root (subfolders allowed)."""
    target = _editor_rel_path(body.filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.code, encoding="utf-8", newline="\n")
    return {"ok": True, "path": str(target)}


@app.get("/api/editor/open")
async def open_editor_file(path: str):
    """Load a scratch file back into the buffer."""
    target = _editor_rel_path(path)
    if not target.is_file():
        raise HTTPException(404, f"No such file: {path}")
    content = target.read_text(encoding="utf-8", errors="replace")
    if len(content) > _EDITOR_OPEN_CAP:
        raise HTTPException(422, f"File too large to open ({len(content)} chars, cap {_EDITOR_OPEN_CAP})")
    # rel is slash-normalized — the frontend uses it as the buffer's filename
    rel = target.relative_to(editor_root()).as_posix()
    return {"ok": True, "path": str(target), "rel": rel, "content": content}


@app.post("/api/editor/mkdir")
async def editor_mkdir(body: EditorFileBody):
    target = _editor_rel_path(body.filename)
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "path": str(target)}


@app.get("/api/editor/tree")
async def editor_tree():
    """Recursive file tree for the explorer (caps: depth 5, 800 entries)."""
    root = editor_root()
    root.mkdir(parents=True, exist_ok=True)
    out = {"name": "", "dirs": [], "files": []}
    budget = {"n": 800}

    def _fill(dir_path, node, depth):
        if depth > 5 or budget["n"] <= 0:
            return
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return
        for entry in entries:
            if budget["n"] <= 0:
                return
            budget["n"] -= 1
            if entry.is_dir():
                sub = {"name": entry.name, "dirs": [], "files": []}
                _fill(entry, sub, depth + 1)
                node["dirs"].append(sub)
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                node["files"].append({"name": entry.name, "size": size})

    _fill(root, out, 1)
    return out


class DownloadBody(BaseModel):
    content: str
    filename: str | None = None
    css: str | None = None
    js: str | None = None
    kind: str | None = None  # "html" (default) or "svg"


def _inject_tag(html: str, tag: str, anchor: str, skip_pattern: str) -> str:
    """Insert tag before anchor (</head> or </body>) unless skip_pattern matches."""
    if re.search(skip_pattern, html, re.IGNORECASE):
        return html
    if re.search(anchor, html, re.IGNORECASE):
        return re.sub(anchor, tag + r"\g<0>", html, count=1, flags=re.IGNORECASE)
    return html + "\n" + tag if anchor == r"</body\s*>" else tag + "\n" + html


class WorkspaceMkdirBody(BaseModel):
    path: str


@app.post("/api/workspace/mkdir")
async def workspace_mkdir(body: WorkspaceMkdirBody):
    res = workspace.mkdir(body.path)
    if not res.get("ok"):
        raise HTTPException(422, res.get("error"))
    return {"ok": True, **res}


@app.get("/api/workspace/read")
async def workspace_read(path: str = ""):
    """Scoped file read for the artifact preview bridge."""
    res = workspace.read(path)
    if not res.get("ok"):
        raise HTTPException(422 if "denied" in res.get("error", "") else 404, res.get("error"))
    return res


@app.get("/api/workspace/ls")
async def workspace_ls(path: str = ""):
    try:
        res = workspace.ls(path)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if not res.get("ok"):
        raise HTTPException(404, res.get("error"))
    return res


@app.post("/api/download")
async def download_artifact(body: DownloadBody):
    css = (body.css or "").strip()
    js = (body.js or "").strip()
    total = len(body.content) + len(css) + len(js)
    if total > 5_000_000:
        raise HTTPException(413, "Artifact too large (5MB limit)")
    name = body.filename or "artifact"
    name = re.sub(r"[^A-Za-z0-9_-]", "-", name).strip("-") or "artifact"
    downloads = Path.home() / "Downloads"
    try:
        downloads.mkdir(exist_ok=True)
        target_dir = downloads
    except OSError:
        target_dir = Path.home()
    # SVG artifact: single .svg file in Downloads (no project folder path).
    kind = (body.kind or "html").lower()
    if kind not in ("html", "svg"):
        raise HTTPException(422, "kind must be 'html' or 'svg'")
    if kind == "svg":
        if "<svg" not in body.content[:2000].lower():
            raise HTTPException(422, "Not an SVG document")
        final = None
        for i in range(1, 1000):
            candidate = target_dir / f"su1ra-{name}{'' if i == 1 else f'-{i}'}.svg"
            if not candidate.exists():
                final = candidate
                break
        if final is None:
            raise HTTPException(409, "Could not pick a file name")
        final.write_text(body.content, encoding="utf-8")
        return {"ok": True, "path": str(final)}
    if not css and not js:
        final = None
        for i in range(1, 1000):
            candidate = target_dir / f"su1ra-{name}{'' if i == 1 else f'-{i}'}.html"
            if not candidate.exists():
                final = candidate
                break
        if final is None:
            raise HTTPException(409, "Could not pick a file name")
        final.write_text(body.content, encoding="utf-8")
        return {"ok": True, "path": str(final)}
    # Project folder: index.html + style.css + script.js, wired together.
    project = None
    for i in range(1, 1000):
        candidate = target_dir / f"su1ra-{name}{'' if i == 1 else f'-{i}'}"
        if not candidate.exists():
            project = candidate
            break
    if project is None:
        raise HTTPException(409, "Could not pick a folder name")
    project.mkdir()
    html = body.content
    if css:
        html = _inject_tag(
            html,
            '<link rel="stylesheet" href="./style.css">',
            r"</head\s*>",
            r"<link[^>]*stylesheet",
        )
        (project / "style.css").write_text(body.css.strip() + "\n", encoding="utf-8")
    if js:
        html = _inject_tag(
            html,
            '<script src="./script.js"></script>',
            r"</body\s*>",
            r"<script[^>]*src=",
        )
        (project / "script.js").write_text(body.js.strip() + "\n", encoding="utf-8")
    (project / "index.html").write_text(html, encoding="utf-8")
    return {"ok": True, "path": str(project)}


@app.get("/{full_path:path}")
async def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "Not found")
    if DIST.is_dir():
        candidate = (DIST / full_path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(DIST.resolve())):
            if candidate.name == "index.html":
                return serve_index()
            return FileResponse(candidate)
        index = DIST / "index.html"
        if index.is_file():
            return serve_index()
    raise HTTPException(404, "Not found")


def serve_index():
    """Serve index.html with the saved theme stamped in.

    React boots with hardcoded defaults and only applies the saved
    accent/brightness after /api/settings lands — a visible flash.
    Inlining the DB values as window.__SU1RA_THEME__ lets the first
    paint already use them (App.jsx reads it for initial state).
    """
    html = (DIST / "index.html").read_text(encoding="utf-8")
    accent = (store.get_setting("accent") or "#bf264a").strip().lower()
    if not re.fullmatch(r"#[0-9a-f]{6}", accent):
        accent = "#bf264a"

    def _int(key, default, lo, hi):
        try:
            return max(lo, min(hi, int(store.get_setting(key) or default)))
        except (TypeError, ValueError):
            return default

    theme = (
        "<script>window.__SU1RA_THEME__="
        + json.dumps({
            "accent": accent,
            "bg_brightness": _int("bg_brightness", 100, 0, 150),
            "bg_contrast": _int("bg_contrast", 100, 0, 150),
        })
        + ";window.__SU1RA_DEBUG__="
        + ("true" if os.environ.get("SU1RA_DEBUG") == "1" else "false")
        + ";</script>"
    )
    if "</head>" in html:
        html = html.replace("</head>", theme + "</head>", 1)
    else:
        html = theme + html
    return HTMLResponse(html)
