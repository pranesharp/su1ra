import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from store import get_setting

DEFAULT_URL = "http://localhost:11434"


def base_url():
    url = get_setting("ollama_url") or os.environ.get("OLLAMA_URL") or DEFAULT_URL
    return url.rstrip("/")


_capabilities_cache = {}
_ctx_cache = {}


async def model_supports_tools(model):
    if model in _capabilities_cache:
        return _capabilities_cache[model]
    base = base_url()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{base}/api/show", json={"model": model})
            resp.raise_for_status()
            caps = resp.json().get("capabilities") or []
    except Exception:
        return False
    supported = "tools" in caps
    _capabilities_cache[model] = supported
    return supported


async def model_context_length(model):
    if model in _ctx_cache:
        return _ctx_cache[model]
    base = base_url()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{base}/api/show", json={"model": model})
            resp.raise_for_status()
            info = resp.json().get("model_info") or {}
            ctx = 0
            for key, value in info.items():
                if key.endswith(".context_length") and isinstance(value, int):
                    ctx = max(ctx, value)
    except Exception:
        return 0
    _ctx_cache[model] = ctx
    return ctx


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


async def stream_chat(model, messages, system_prompt="", temperature=0.7, num_ctx=0, tools=None):
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
    if tools:
        payload["tools"] = tools
    t0 = time.perf_counter()
    ttft = None
    t_first_content = None
    think_start = None
    think_end = None
    think_tokens = 0
    output_tokens = 0
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
                    tool_calls = msg.get("tool_calls") or []
                    if tool_calls:
                        yield {"tool_calls": tool_calls}
                    thinking = msg.get("thinking") or ""
                    content = msg.get("content") or ""
                    now = time.perf_counter()
                    if ttft is None and (thinking or content):
                        ttft = now - t0
                    if thinking:
                        if not saw_thinking:
                            saw_thinking = True
                            yield {"delta": "<think>\n"}
                        think_tokens += 1
                        if think_start is None:
                            think_start = now
                        yield {"delta": thinking}
                    if content:
                        if saw_thinking:
                            if think_end is None:
                                think_end = now
                            saw_thinking = False
                            yield {"delta": "\n</think>\n\n"}
                        output_tokens += 1
                        if t_first_content is None:
                            t_first_content = now
                        yield {"delta": content}
                    if obj.get("done"):
                        if saw_thinking:
                            yield {"delta": "\n</think>"}
                        prompt_count = obj.get("prompt_eval_count") or 0
                        prompt_dur = obj.get("prompt_eval_duration") or 0
                        eval_count = obj.get("eval_count") or 0
                        eval_dur = obj.get("eval_duration") or 0
                        output_span = now - t_first_content if t_first_content else 0
                        stats = {
                            "model": model,
                            "prompt_tokens": prompt_count,
                            "prompt_tps": round(prompt_count / (prompt_dur / 1e9), 1) if prompt_count and prompt_dur else None,
                            "ttft": round(ttft, 2) if ttft is not None else None,
                            "think_tokens": think_tokens,
                            "think_tps": round(think_tokens / (think_end - think_start), 1) if think_tokens and think_start and think_end else None,
                            "think_time": round(think_end - think_start, 2) if think_start and think_end else None,
                            "output_tokens": output_tokens,
                            "output_tps": round(output_tokens / output_span, 1) if output_tokens and output_span > 0 else None,
                            "total_time": round(now - t0, 2),
                            "eval_count": eval_count,
                            "eval_tps": round(eval_count / (eval_dur / 1e9), 1) if eval_count and eval_dur else None,
                        }
                        yield {"stats": stats}
                        yield {"done": True, "eval_count": eval_count}
                        return
    except httpx.HTTPError as exc:
        yield {"error": f"Cannot reach Ollama server at {base} ({exc.__class__.__name__})"}
