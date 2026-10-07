import asyncio
import atexit
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


def engine_env():
    """Extra env for a server Su1ra spawns, from the `engine` setting.

    - auto: no overrides (Ollama picks; note it drops iGPUs unless asked).
    - cpu: hide every GPU backend -> CPU inference.
    - gpu: keep auto-detect but stop dropping integrated GPUs; Vulkan itself
      is only forced when `engine_vulkan` is on (experimental, Intel/XPU).
    """
    engine = (get_setting("engine") or "auto").strip().lower()
    if engine == "cpu":
        return {
            "CUDA_VISIBLE_DEVICES": "-1",
            "HIP_VISIBLE_DEVICES": "-1",
            "ROCR_VISIBLE_DEVICES": "-1",
            "OLLAMA_VULKAN": "0",
            "GGML_VK_VISIBLE_DEVICES": "-1",
        }
    if engine == "gpu":
        env = {"OLLAMA_IGPU_ENABLE": "1"}
        if get_setting("engine_vulkan") == "1":
            env["OLLAMA_VULKAN"] = "1"
        return env
    return {}


def _run_capture(cmd, timeout=8):
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if proc.returncode == 0:
            return proc.stdout.decode(errors="replace")
    except Exception:
        pass
    return ""


def detect_gpus():
    """Best-effort GPU discovery for the settings UI. Never raises."""
    info = {"nvidia": False, "nvidia_names": [], "vulkan": False, "intel": "", "amd": ""}
    candidates = [["nvidia-smi", "-L"]]
    if os.name == "nt":
        candidates.append([r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe", "-L"])
    for cmd in candidates:
        names = [line.strip() for line in _run_capture(cmd).splitlines() if "GPU" in line]
        if names:
            info["nvidia"] = True
            info["nvidia_names"] = names
            break
    try:
        import ctypes.util

        info["vulkan"] = (
            ctypes.util.find_library("vulkan-1" if os.name == "nt" else "vulkan") is not None
        )
    except Exception:
        pass
    names = []
    if os.name == "nt":
        out = _run_capture(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
            ],
            timeout=12,
        )
        names = [line.strip() for line in out.splitlines() if line.strip()]
    else:
        out = _run_capture(["sh", "-c", "lspci 2>/dev/null | grep -iE 'vga|3d|display'"])
        names = [line.strip() for line in out.splitlines() if line.strip()]
    for name in names:
        low = name.lower()
        if "intel" in low and not info["intel"]:
            info["intel"] = name
        if ("amd" in low or "radeon" in low) and not info["amd"]:
            info["amd"] = name
    return info


def has_spawned():
    return _spawned_proc is not None and _spawned_proc.poll() is None


_capabilities_cache = {}
_ctx_cache = {}
_spawned_proc = None


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


def models_dir():
    candidates = []
    if os.environ.get("OLLAMA_MODELS"):
        candidates.append(Path(os.environ["OLLAMA_MODELS"]))
    candidates.append(Path.home() / ".ollama" / "models")
    candidates.append(Path.home() / ".local" / "share" / "ollama" / "models")
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "Ollama" / "models")
    for c in candidates:
        if c.is_dir():
            return c
    return Path.home() / ".local" / "share" / "ollama" / "models"


async def disk_free():
    try:
        return shutil.disk_usage(str(models_dir())).free
    except Exception:
        return 0


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


async def unload_model(model):
    """Drop a loaded model from the server (free its memory).

    Best-effort: a minimal 1-token chat with keep_alive 0 is used because it
    validates on every Ollama version (unlike promptless bodies), then the
    server unloads the model right after. Returns True when the server
    accepted the unload.
    """
    if not model:
        return False
    base = base_url()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": " "}],
                    "stream": False,
                    "keep_alive": 0,
                    "think": False,
                    "options": {"num_predict": 1},
                },
            )
            return resp.status_code == 200
    except Exception:
        return False


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
    import sys

    app_root = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent
    )
    for sub in ("ollama", "ollama/bin"):
        for name in ("ollama.exe", "ollama"):
            p = app_root / sub / name
            if p.exists():
                return str(p)
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
    global _spawned_proc
    _spawned_proc = subprocess.Popen(
        [binary, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=(os.name != "nt"),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env={**os.environ, **engine_env()},
    )
    for _ in range(120):
        if (await server_status())["ok"]:
            return {"ok": True, "started": True, "url": base}
        await asyncio.sleep(0.5)
    return {"ok": False, "error": f"ollama did not come up at {base} within 60s"}


def stop_spawned():
    """Stop the ollama server, but ONLY if this backend spawned it.

    Never touches a server the user was already running. Returns True
    when a spawned process was actually stopped.
    """
    global _spawned_proc
    proc, _spawned_proc = _spawned_proc, None
    if proc is None or proc.poll() is not None:
        return False
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return True


def _stop_spawned_quiet():
    try:
        stop_spawned()
    except Exception:
        pass


atexit.register(_stop_spawned_quiet)


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


def normalize_think_param(think):
    if think is None:
        return None
    if isinstance(think, bool):
        return think
    text = str(think).strip().lower()
    if text in ("", "auto", "default", "none"):
        return None
    if text in ("on", "true", "1"):
        return True
    if text in ("off", "false", "0"):
        return False
    if text in ("low", "medium", "high", "max"):
        return text
    return None


def friendly_load_error(text):
    """Map fatal llama-server load failures to an actionable message.

    Returns the friendly string, or None when the error should pass through
    verbatim (genuine server/config errors the user should see raw).
    """
    low = text.lower()
    if any(k in low for k in ("killed", "out of memory", "out-of-memory", "oom", "cannot allocate", "not enough memory")):
        return "model too large for this machine's memory — try a smaller variant, a lower quant, or reduce context length"
    if any(k in low for k in ("startup failed", "failed to initialize", "failed to create")):
        return "ollama couldn't start the model on this machine — usually out of memory: close other apps, lower the context length, or try a smaller model"
    return None


async def stream_chat(model, messages, system_prompt="", temperature=0.7, num_ctx=0, tools=None, think=None):
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
    think_param = normalize_think_param(think)
    if think_param is not None:
        payload["think"] = think_param
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
                    friendly = friendly_load_error(body)
                    if friendly:
                        yield {"error": friendly}
                    else:
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
                        friendly = friendly_load_error(obj["error"])
                        yield {"error": friendly or obj["error"]}
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
