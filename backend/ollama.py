import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx

from store import get_setting

DEFAULT_URL = "http://localhost:11434"


def base_url():
    url = get_setting("ollama_url") or os.environ.get("OLLAMA_URL") or DEFAULT_URL
    return url.rstrip("/")


async def server_status():
    base = base_url()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{base}/api/version")
            resp.raise_for_status()
            return {"ok": True, "version": resp.json().get("version"), "url": base}
    except Exception:
        return {"ok": False, "version": None, "url": base}


def find_binary():
    found = shutil.which("ollama")
    if found:
        return found
    for candidate in ("/usr/local/bin/ollama", "/usr/bin/ollama"):
        if Path(candidate).exists():
            return candidate
    return None


async def ensure_running():
    base = base_url()
    if (await server_status())["ok"]:
        return {"ok": True, "started": False, "url": base}
    binary = find_binary()
    if not binary:
        return {"ok": False, "error": "ollama binary not found — install ollama or add it to PATH"}
    subprocess.Popen(
        [binary, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=(os.name != "nt"),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for _ in range(120):
        if (await server_status())["ok"]:
            return {"ok": True, "started": True, "url": base}
        await asyncio.sleep(0.5)
    return {"ok": False, "error": f"ollama did not come up at {base} within 60s"}


async def list_models():
    base = base_url()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/api/tags")
            resp.raise_for_status()
            return [
                {"name": m["name"], "size": m.get("size"), "details": m.get("details", {})}
                for m in resp.json().get("models", [])
            ]
    except Exception:
        return []


async def stream_chat(model, messages, system_prompt="", temperature=0.7, num_ctx=0):
    base = base_url()
    payload_messages = (
        [{"role": "system", "content": system_prompt}] if system_prompt.strip() else []
    ) + messages
    options = {"temperature": temperature}
    if num_ctx and num_ctx > 0:
        options["num_ctx"] = num_ctx
    payload = {
        "model": model,
        "messages": payload_messages,
        "stream": True,
        "options": options,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5.0)) as client:
            async with client.stream("POST", f"{base}/api/chat", json=payload) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode(errors="replace")[:300]
                    yield {"error": f"Ollama returned {resp.status_code}: {body}"}
                    return
                saw_thinking = False
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "error" in obj:
                        yield {"error": obj["error"]}
                        return
                    msg = obj.get("message") or {}
                    thinking = msg.get("thinking") or ""
                    content = msg.get("content") or ""
                    if thinking:
                        if not saw_thinking:
                            saw_thinking = True
                            yield {"delta": "<think>\n"}
                        yield {"delta": thinking}
                    if content:
                        if saw_thinking and not content.lstrip().startswith("<think>"):
                            saw_thinking = False
                            yield {"delta": "\n</think>\n\n"}
                        yield {"delta": content}
                    if obj.get("done"):
                        if saw_thinking:
                            yield {"delta": "\n</think>"}
                        yield {"done": True, "eval_count": obj.get("eval_count")}
                        return
    except httpx.HTTPError as exc:
        yield {"error": f"Cannot reach Ollama server at {base} ({exc.__class__.__name__})"}
