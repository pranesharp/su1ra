import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import ollama
import runner
import store

if os.name == "posix":
    import ptyrunner

if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST = PROJECT_ROOT / "frontend" / "dist"

store.init_db()

app = FastAPI(title="Su1ra")
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
    }
]


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
    if not out.strip():
        return f"[no output — {status}]"
    return f"{out}\n[{status}]"


class ChatRequest(BaseModel):
    conversation_id: int
    content: str
    model: str = ""


class ConversationCreate(BaseModel):
    title: str = ""
    model: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    context_length: int = 0


class ConversationUpdate(BaseModel):
    title: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    temperature: float | None = None
    context_length: int | None = None


class SettingsUpdate(BaseModel):
    ollama_url: str | None = None
    accent: str | None = None
    show_stats: bool | None = None
    ide_open: bool | None = None
    ide_width: int | None = None


class RunRequest(BaseModel):
    code: str
    language: str = "python"


class RunInput(BaseModel):
    run_id: str
    text: str


@app.get("/api/status")
async def status():
    return await ollama.server_status()


@app.get("/api/models")
async def models():
    return {"models": await ollama.list_models()}


@app.get("/api/settings")
async def get_settings():
    return {
        "ollama_url": store.get_setting("ollama_url") or ollama.DEFAULT_URL,
        "accent": store.get_setting("accent") or "#bf264a",
        "show_stats": store.get_setting("show_stats") == "1",
        "ide_open": store.get_setting("ide_open") == "1",
        "ide_width": int(store.get_setting("ide_width") or 460),
    }


@app.patch("/api/settings")
async def update_settings(body: SettingsUpdate):
    if (
        body.ollama_url is None
        and body.accent is None
        and body.show_stats is None
        and body.ide_open is None
        and body.ide_width is None
    ):
        raise HTTPException(422, "nothing to update")
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
    if body.ide_width is not None:
        if not 280 <= body.ide_width <= 1200:
            raise HTTPException(422, "ide_width must be between 280 and 1200")
        store.set_setting("ide_width", str(body.ide_width))
    return {
        "ok": True,
        "ollama_url": store.get_setting("ollama_url") or ollama.DEFAULT_URL,
        "accent": store.get_setting("accent") or "#bf264a",
        "show_stats": store.get_setting("show_stats") == "1",
        "ide_open": store.get_setting("ide_open") == "1",
        "ide_width": int(store.get_setting("ide_width") or 460),
    }


@app.post("/api/eject")
async def eject():
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/IM", "ollama.exe"], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "ollama serve"], capture_output=True)
    for _ in range(10):
        if not (await ollama.server_status())["ok"]:
            break
        await asyncio.sleep(0.2)
    else:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/IM", "ollama.exe"], capture_output=True)
        else:
            subprocess.run(["pkill", "-9", "-f", "ollama serve"], capture_output=True)
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
    return store.create_conversation(
        body.title, body.model, body.system_prompt, body.temperature, body.context_length
    )


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: int):
    conversation = store.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return {"conversation": conversation, "messages": store.get_messages(conversation_id)}


@app.patch("/api/conversations/{conversation_id}")
async def update_conversation(conversation_id: int, body: ConversationUpdate):
    updated = store.update_conversation(
        conversation_id,
        title=body.title,
        model=body.model,
        system_prompt=body.system_prompt,
        temperature=body.temperature,
        context_length=body.context_length,
    )
    if not updated:
        raise HTTPException(404, "Conversation not found")
    return updated


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int):
    if not store.delete_conversation(conversation_id):
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}


@app.post("/api/chat")
async def chat(body: ChatRequest):
    conversation = store.get_conversation(body.conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    content = body.content.strip()
    if not content:
        raise HTTPException(422, "Empty message")
    model = body.model or conversation["model"]
    if not model:
        raise HTTPException(422, "No model selected")

    store.add_message(body.conversation_id, "user", content)
    if not conversation["title"]:
        store.update_conversation(body.conversation_id, title=content[:60])
    history = build_history(store.get_messages(body.conversation_id))
    tools = TOOLS if await ollama.model_supports_tools(model) else None
    sys_prompt = conversation["system_prompt"]
    if tools:
        directive = (
            "You have the run_python tool. Use it proactively whenever the task involves "
            "computation, running code, or checking output — call it instead of guessing results."
        )
        sys_prompt = f"{sys_prompt}\n\n{directive}" if sys_prompt.strip() else directive

    async def generator():
        working = list(history)

        for round_idx in range(MAX_TOOL_ROUNDS + 1):
            with_tools = round_idx < MAX_TOOL_ROUNDS
            text = ""
            stats = None
            pending_calls = []
            saved = False
            consumed = False

            def save():
                nonlocal saved
                if saved or (not text.strip() and not pending_calls):
                    return
                store.add_message(
                    body.conversation_id,
                    "assistant",
                    "" if consumed else text.strip(),
                    stats,
                    tool_calls=[finalize_tool_call(tc) for tc in pending_calls] if pending_calls else None,
                )
                saved = True

            try:
                async for chunk in ollama.stream_chat(
                    model,
                    working,
                    sys_prompt,
                    conversation["temperature"],
                    conversation["context_length"],
                    tools=tools if with_tools else None,
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
                yield json.dumps({"done": True, "eval_count": eval_count}) + "\n"
                return

            finalized = [finalize_tool_call(tc) for tc in pending_calls]
            working.append({"role": "assistant", "content": "" if consumed else text.strip(), "tool_calls": finalized})
            for call in finalized:
                name = call["function"]["name"]
                arguments = call["function"]["arguments"]
                code = str(arguments.get("code") or "") if name == "run_python" else ""
                yield json.dumps({"tool_start": {"name": name}}) + "\n"
                if name != "run_python":
                    result = None
                    result_text = f"Unknown tool: {name}. The only available tool is run_python."
                else:
                    try:
                        result = await runner.run_python(code)
                        result_text = tool_result_text(result)
                    except Exception as exc:
                        result = None
                        result_text = f"[execution error: {exc}]"
                row = store.add_message(body.conversation_id, "tool", result_text)
                working.append({"role": "tool", "content": result_text})
                yield json.dumps(
                    {
                        "tool": {
                            "name": name,
                            "code": code,
                            "output": result_text,
                            "id": row["id"],
                            "exit": result["exit"] if result else None,
                            "replaces_text": consumed,
                        }
                    }
                ) + "\n"

    return StreamingResponse(generator(), media_type="application/x-ndjson")


@app.post("/api/run")
async def run(body: RunRequest):
    run_id = uuid.uuid4().hex
    if not body.code.strip():
        raise HTTPException(422, "Empty code")
    if body.language != "python":
        raise HTTPException(422, "Only python is supported")
    scratch = store.DATA_DIR / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    if HAS_PTY:
        return StreamingResponse(pty_generator(run_id, body.code, scratch), media_type="application/x-ndjson")

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
                sys.executable,
                "-u",
                "-c",
                body.code,
                cwd=scratch,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
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


async def pty_generator(run_id, code, scratch):
    sess = ptyrunner.PtySession(code, scratch)
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


@app.get("/{full_path:path}")
async def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "Not found")
    if DIST.is_dir():
        candidate = (DIST / full_path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(DIST.resolve())):
            return FileResponse(candidate)
        index = DIST / "index.html"
        if index.is_file():
            return FileResponse(index)
    raise HTTPException(404, "Not found")
