import asyncio
import os
import platform
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import httpx

from ollama import base_url, disk_free, ensure_running

if getattr(sys, "frozen", False):
    APP_ROOT = Path(sys.executable).resolve().parent
else:
    APP_ROOT = Path(__file__).resolve().parent.parent

ARTIFACTS = {
    "windows": "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip",
    "linux": "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tar.zst",
}

_install_lock = asyncio.Lock()


def artifact_url():
    system = platform.system().lower()
    return ARTIFACTS.get(system)


def target_dir():
    return APP_ROOT / "ollama"


def installed_binary():
    d = target_dir()
    for sub in (".", "bin"):
        for name in ("ollama.exe", "ollama"):
            p = d / sub / name
            if p.exists() and p.stat().st_mode & 0o111 or (p.exists() and name.endswith(".exe")):
                return str(p)
    return None


def _extract(archive: Path, dest: Path):
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
        _unlink_best_effort(archive)
        return
    magic = archive.open("rb").read(4)
    if magic.startswith(b"\x28\xb5\x2f\xfd"):
        mode = "r:zst"
    elif magic.startswith(b"\x1f\x8b"):
        mode = "r:gz"
    else:
        mode = "r:"
    with tarfile.open(archive, mode) as t:
        t.extractall(dest, filter="data")
    _unlink_best_effort(archive)


def _unlink_best_effort(path: Path):
    """Delete best-effort: on Windows an antivirus/indexer lock must never
    fail an otherwise good install (this exact WinError 32 orphaned a
    0-byte llama-server.exe before). Leftovers are swept next run."""
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _sweep_stale_downloads(dest: Path):
    for stale in dest.glob("*.download"):
        _unlink_best_effort(stale)


async def install(send):
    """Download the Ollama server artifact, extract into the app dir, start it.

    Reports progress via send(dict): {pct, got, total} while downloading,
    {status: extracting|starting server}, then {ok: True} or {error: str}.
    """
    if _install_lock.locked():
        await send({"error": "an install is already running"})
        return
    async with _install_lock:
        url = artifact_url()
        if not url:
            await send({"error": "automatic install is not supported on this platform — get ollama from https://ollama.com/download"})
            return
        dest = target_dir()
        dest.mkdir(parents=True, exist_ok=True)
        _sweep_stale_downloads(dest)
        free = await disk_free()
        # mkstemp returns an OPEN fd — close it at once. Leaking it locks
        # the file on Windows and the later cleanup unlink dies with
        # WinError 32 (the exact failure in the screenshots).
        fd, tmppath = tempfile.mkstemp(suffix=".download", dir=str(dest))
        os.close(fd)
        tmp = Path(tmppath)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(None, connect=10.0), follow_redirects=True
            ) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        await send({"error": f"download failed: HTTP {resp.status_code}"})
                        return
                    total = int(resp.headers.get("content-length") or 0)
                    if total and free and free < total * 1.1:
                        await send({"error": f"not enough disk space: ollama needs about {total // 1048576} MB, only {free // 1048576} MB free"})
                        return
                    got = 0
                    with open(tmp, "wb") as f:
                        # Per-chunk timeout = stall watchdog. The artifact is
                        # ~1.4GB, so slowness is normal — but a dead connection
                        # must surface instead of sitting at 0% forever.
                        stream = resp.aiter_bytes(1 << 16)
                        while True:
                            try:
                                chunk = await asyncio.wait_for(stream.__anext__(), timeout=90)
                            except StopAsyncIteration:
                                break
                            except asyncio.TimeoutError:
                                await send({"error": "download stalled: no data for 90s — check your connection, then try again (it resumes from scratch)"})
                                return
                            f.write(chunk)
                            got += len(chunk)
                            if total:
                                await send({"pct": round(100 * got / total, 1), "got": got, "total": total})
            await send({"status": "extracting"})
            await asyncio.to_thread(_extract, tmp, dest)
            if not installed_binary():
                await send({"error": "downloaded archive did not contain an ollama binary"})
                return
            await send({"status": "starting server"})
            res = await ensure_running()
            if res.get("ok"):
                await send({"ok": True})
            else:
                await send({"error": "ollama is installed but did not start — restart Su1ra, or run 'ollama serve' once"})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await send({"error": f"install failed: {e}"})
        finally:
            _unlink_best_effort(tmp)
