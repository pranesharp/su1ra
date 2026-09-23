import asyncio
import os
import sys

from store import DATA_DIR

TIMEOUT_SECONDS = 30
MAX_LINES = 2000
MAX_BYTES = 1024 * 1024


async def run_python(code):
    scratch = DATA_DIR / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        code,
        cwd=scratch,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
    )
    lines = []
    state = {"bytes": 0, "capped": False}

    def store_line(raw):
        if state["capped"]:
            return
        state["bytes"] += len(raw) + 1
        if len(lines) >= MAX_LINES or state["bytes"] > MAX_BYTES:
            state["capped"] = True
            lines.append("// output truncated — process killed")
            try:
                proc.kill()
            except Exception:
                pass
            return
        lines.append(raw.decode("utf-8", errors="replace"))

    async def read_stream(stream):
        buf = b""
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                store_line(line)
            if buf:
                store_line(buf)
                buf = b""

    readers = [
        asyncio.create_task(read_stream(proc.stdout)),
        asyncio.create_task(read_stream(proc.stderr)),
    ]
    timed_out = False
    try:
        await asyncio.wait_for(asyncio.gather(*readers), timeout=TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        lines.append("// timeout — killed after 30s")
    except asyncio.CancelledError:
        proc.kill()
        try:
            await asyncio.shield(proc.wait())
        except Exception:
            pass
        raise
    returncode = await proc.wait()
    return {
        "exit": returncode,
        "output": "\n".join(lines),
        "timed_out": timed_out,
        "capped": state["capped"],
    }
