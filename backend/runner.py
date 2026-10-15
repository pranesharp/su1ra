import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import sandbox
from store import DATA_DIR

TIMEOUT_SECONDS = 30
MAX_LINES = 2000
MAX_BYTES = 1024 * 1024
# Name of OUR OWN executable. A child process must never be another Su1ra.
APP_EXE_NAME = Path(sys.executable).name.lower()


def is_app_exe(cand):
    """True if `cand` is the packaged app itself. Frozen, sys.executable IS
    su1ra.exe and the bundle ships no python.exe (only python3xx.dll) — spawning
    it opened a second Su1ra window instead of running the model's code."""
    if not cand:
        return False
    try:
        return Path(cand).name.lower() == APP_EXE_NAME
    except OSError:
        return False


# Windows ships "python.exe" as a zero-byte App Execution Alias stub in
# %LOCALAPPDATA%\Microsoft\WindowsApps: running it opens the Store instead of
# executing code — the last thing a tool run should do. No real interpreter
# lives in a folder named "WindowsApps", so the parent dir names it reliably.
def is_store_alias(cand):
    """True if `cand` is the Microsoft Store python stub, not a real interpreter."""
    if not cand:
        return False
    try:
        p = Path(cand)
        return p.parent.name.lower() == "windowsapps"
    except OSError:
        return False


def python_exe():
    """A real python interpreter, never the app exe. See main.py's editor path —
    both now resolve through here. $SU1RA_PYTHON wins when set (packaged app with
    python off PATH); None means "no interpreter" — report it, don't spawn."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    override = os.environ.get("SU1RA_PYTHON", "").strip()
    if override and Path(override).is_file() and not is_app_exe(override) and not is_store_alias(override):
        return override
    for name in ("python", "python3", "py"):
        cand = shutil.which(name)
        if cand and not is_app_exe(cand) and not is_store_alias(cand):
            return cand
    return None


def child_spawn_kwargs():
    """Windows: this app is a windowed exe with no console to inherit, so a
    console-subsystem child gets its OWN terminal window (a flash, or — with a
    GUI parent — a window that stays). CREATE_NO_WINDOW suppresses it. Empty on
    POSIX: passing the kwarg at all there is at best a no-op, at worst a
    ValueError/TypeError depending on the Python version."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def interpreter_root():
    exe = python_exe()
    exe = Path(os.path.abspath(exe or sys.executable))
    venv_root = exe.parents[1]
    if (venv_root / "pyvenv.cfg").exists():
        return venv_root
    return exe.parent


async def run_python(code, sandboxed=True, cwd=None, backend="auto"):
    scratch = DATA_DIR / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    workdir = Path(cwd) if cwd else scratch
    try:
        workdir.mkdir(parents=True, exist_ok=True)
    except OSError:
        workdir = scratch

    exe = python_exe()
    mode = "off"
    unavailable_reason = ""
    via_stdin = False
    cmd = None
    if sandboxed and backend != "off":
        if os.name == "nt" and backend in ("auto", "wsl"):
            # Never from the loop: a cold-starting distro blocks for seconds.
            probe = await asyncio.to_thread(sandbox.wsl_probe)
            if probe["ok"]:
                wrapped = sandbox.wsl_wrap(workdir, timeout=TIMEOUT_SECONDS)
                if wrapped:
                    cmd = wrapped
                    via_stdin = True
                    mode = "wsl"
                else:
                    mode = "unavailable"
                    unavailable_reason = probe["reason"]
            else:
                # The interpreter lives INSIDE WSL — a Windows python is not
                # needed for this branch, so no no_python early return here.
                mode = "unavailable"
                unavailable_reason = probe["reason"]
        else:
            if not exe:
                return {
                    "exit": -1,
                    "output": "python interpreter not found — install Python or set the "
                              "SU1RA_PYTHON environment variable to its path",
                    "timed_out": False,
                    "capped": False,
                    "sandbox": "off",
                    "error": "no_python",
                }
            plain = [os.path.abspath(exe), "-u", "-c", code]
            wrapped = sandbox.wrap(plain, workdir, ro_dirs=[interpreter_root()])
            if wrapped:
                cmd = wrapped
                mode = "on"
            else:
                mode = "unavailable"
    if cmd is None:
        if not exe:
            return {
                "exit": -1,
                "output": "python interpreter not found — install Python or set the "
                          "SU1RA_PYTHON environment variable to its path",
                "timed_out": False,
                "capped": False,
                "sandbox": "off",
                "error": "no_python",
            }
        cmd = [os.path.abspath(exe), "-u", "-c", code]
    spawn_kwargs = dict(cwd=str(workdir), **child_spawn_kwargs())
    if via_stdin:
        spawn_kwargs["stdin"] = asyncio.subprocess.PIPE
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        **spawn_kwargs,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
    )
    if via_stdin:
        try:
            proc.stdin.write(code.encode())
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass  # inner python already exited (e.g. interpreter failed)
        finally:
            proc.stdin.close()
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
    # The bwrap profile bounds compute INSIDE at TIMEOUT_SECONDS
    # (/usr/bin/timeout in the argv). The outer cap must be looser so a WSL
    # cold start isn't counted against the model's 30s.
    outer_timeout = TIMEOUT_SECONDS + 15 if via_stdin else TIMEOUT_SECONDS
    try:
        await asyncio.wait_for(asyncio.gather(*readers), timeout=outer_timeout)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        lines.append(f"// timeout — killed after {outer_timeout}s")
    except asyncio.CancelledError:
        proc.kill()
        try:
            await asyncio.shield(proc.wait())
        except Exception:
            pass
        raise
    returncode = await proc.wait()
    if via_stdin and not timed_out and returncode in (124, 137):
        # /usr/bin/timeout exits 124 after SIGKILL'ing the payload (137 is the
        # killed python's own status as seen through bwrap) — same meaning as
        # the outer timeout, report it as the cap doing its job.
        timed_out = True
        lines.append(f"// timeout — killed after {TIMEOUT_SECONDS}s")
    result = {
        "exit": returncode,
        "output": "\n".join(lines),
        "timed_out": timed_out,
        "capped": state["capped"],
        "sandbox": mode,
    }
    if unavailable_reason:
        result["sandbox_reason"] = unavailable_reason
    return result
