import asyncio
import json

import httpx

from ollama import base_url, disk_free

_pulls = {}


def status_for(model):
    return _pulls.get(model)


def cancel(model):
    task = _pulls.pop(model, None)
    if task:
        task.cancel()


async def pull(model, send):
    """Stream an Ollama pull as NDJSON progress lines via send(dict).

    Registers itself so a second pull of the same model is rejected and
    cancels are deliverable. Cleans up on completion, error, or disconnect.
    """
    if model in _pulls:
        await send({"error": f"a pull for {model} is already running"})
        return
    _pulls[model] = asyncio.current_task()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=5.0)) as client:
            async with client.stream(
                "POST",
                f"{base_url()}/api/pull",
                json={"model": model, "stream": True},
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    try:
                        err = json.loads(body).get("error", body)
                    except json.JSONDecodeError:
                        err = body
                    await send({"error": err or f"ollama returned {resp.status_code}"})
                    return
                size_checked = False
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if evt.get("error"):
                        await send({"error": evt["error"]})
                        return
                    total = evt.get("total") or 0
                    if total and not size_checked:
                        size_checked = True
                        free = await disk_free()
                        if free and free < total * 1.1:
                            await client.request("DELETE", f"{base_url()}/api/pull", json={"model": model})
                            await send({"error": f"not enough disk space: model needs {total // 1048576} MB, only {free // 1048576} MB free"})
                            return
                    out = {"status": evt.get("status", "pulling")}
                    if evt.get("total") and evt.get("completed") is not None:
                        out.update(
                            total=evt["total"],
                            completed=evt["completed"],
                            pct=round(100 * evt["completed"] / evt["total"], 1),
                        )
                    if evt.get("digest"):
                        out["digest"] = evt["digest"]
                    done = out["status"] == "success"
                    await send(out)
                    if done:
                        return
                await send({"status": "success"})
    except asyncio.CancelledError:
        raise
    finally:
        _pulls.pop(model, None)
