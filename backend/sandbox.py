import os
import platform
import shutil
import subprocess
import time


def find_bwrap():
    if platform.system() != "Linux":
        return None
    return shutil.which("bwrap")


def wrap(cmd, writable_dir, ro_dirs=()):
    """Wrap cmd in a bubblewrap sandbox, or return None if unavailable."""
    bwrap = find_bwrap()
    if not bwrap:
        return None
    home = os.path.expanduser("~")
    writable = str(writable_dir)
    # Mount order matters: read-only root first, then an empty tmpfs over the
    # home directory (hides all user data), then specific paths re-exposed
    # through that tmpfs — the writable scratch dir and the interpreter
    # (venv) read-only, since it lives under home too.
    mounts = []
    for ro in ro_dirs:
        mounts += ["--ro-bind", str(ro), str(ro)]
    return [
        bwrap,
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--die-with-parent",
        "--new-session",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--ro-bind", "/", "/",
        "--tmpfs", home,
        *mounts,
        "--bind", writable, writable,
        *cmd,
    ]


# --- WSL sandbox backend (Windows) -------------------------------------------
# Proven end-to-end 2026-10-16 (report/report/wsl-sandbox-handoff.md):
# `wsl.exe -d <distro> -u root --cd / -e bwrap <args> --
#  /usr/bin/timeout -s KILL 30 python3 -I -u -` with the model's code piped on
# STDIN — never in the argv, so no quoting/escaping of model code through
# wsl.exe. Inside: uid 65534 (nobody), /usr ro, tmpfs /tmp + HOME, only the
# workdir bound in, no /mnt (Windows drives invisible), network off.
# Gotchas (all hit live): wsl.exe's OWN messages are UTF-16 with trailing NULs
# (the inner process's output crosses as plain UTF-8); `which` does not exist
# on Arch — probe with `command -v`; bwrap/python3 live in /usr/sbin.
WSL_OK_CACHE = 600.0
WSL_FAIL_CACHE = 60.0
_wsl_state = {"expire": 0.0, "ok": False, "reason": "", "distro": ""}


def win_to_wsl(path):
    """C:\\Users\\x\\y → /mnt/c/Users/x/y (drvfs). Computed directly — a
    wslpath spawn per run is wasted latency."""
    drive, rest = os.path.splitdrive(os.path.normpath(str(path)))
    if not drive:
        return "/" + rest.replace("\\", "/").lstrip("/")
    return "/mnt/" + drive[0].lower() + "/" + rest.replace("\\", "/").lstrip("/")


def _decode_wsl(raw):
    """wsl.exe's own messages are UTF-16-LE with trailing NULs; decide on the
    NUL bytes instead of guessing an encoding."""
    if not raw:
        return ""
    if b"\x00" in raw:
        return raw.decode("utf-16-le", errors="replace").replace("\x00", "").strip()
    return raw.decode("utf-8", errors="replace").strip()


def _run_wsl(args, timeout=20):
    from runner import child_spawn_kwargs  # deferred: runner imports sandbox
    try:
        proc = subprocess.run(["wsl.exe"] + args, capture_output=True,
                              timeout=timeout, **child_spawn_kwargs())
        return proc.returncode, _decode_wsl(proc.stdout), _decode_wsl(proc.stderr)
    except FileNotFoundError:
        return -1, "", "wsl.exe not found"
    except subprocess.TimeoutExpired:
        return -1, "", "wsl.exe probe timed out"


def wsl_probe(force=False):
    """{ok, reason, distro} for the bwrap-in-WSL backend. Cached (10 min on
    success, 60s on failure). Safe from a worker thread; never from the event
    loop — a cold-starting distro can block for seconds."""
    now = time.monotonic()
    if not force and now < _wsl_state["expire"]:
        return dict(_wsl_state)
    fresh = {"expire": 0.0, "ok": False, "reason": "WSL not installed", "distro": ""}

    def commit():
        _wsl_state.clear()
        _wsl_state.update(fresh)
        return dict(_wsl_state)

    rc, out, err = _run_wsl(["-l", "-q"])
    if rc != 0:
        fresh["reason"] = f"WSL not available ({err or 'no response'})"
        fresh["expire"] = now + WSL_FAIL_CACHE
        return commit()
    distro = (out.splitlines() or [""])[0].strip()
    if not distro:
        fresh["reason"] = "no WSL distro installed — run 'wsl --install' or install one from the Store"
        fresh["expire"] = now + WSL_FAIL_CACHE
        return commit()
    fresh["distro"] = distro
    rc, out, err = _run_wsl([
        "-d", distro, "-e", "sh", "-c", "command -v bwrap; command -v python3",
    ])
    found = {line.strip() for line in out.splitlines() if line.strip()}
    missing = [n for n in ("bwrap", "python3") if not any(n in line for line in found)]
    if rc != 0 or missing:
        fresh["reason"] = (
            f"WSL distro '{distro}' missing {' + '.join(missing) or 'bwrap/python3'} — "
            "install once with: "
            f"wsl -d {distro} -u root -e sh -c 'pacman -Syu --needed --noconfirm python bubblewrap' "
            "(Debian/Ubuntu distros: sudo apt install python3 bubblewrap)"
        )
        fresh["expire"] = now + WSL_FAIL_CACHE
        return commit()
    fresh["ok"] = True
    fresh["reason"] = ""
    fresh["expire"] = now + WSL_OK_CACHE
    return commit()


def wsl_wrap(workdir, timeout=30):
    """Full wsl.exe argv running python through bwrap inside the WSL distro.
    The model's code is NOT in the argv — the caller pipes it on stdin to the
    final `python3 -I -u -`. None unless the probe has succeeded."""
    if not _wsl_state.get("ok"):
        return None
    distro = _wsl_state["distro"]
    src = win_to_wsl(str(workdir))
    return [
        "wsl.exe", "-d", distro, "-u", "root", "--cd", "/", "-e", "bwrap",
        "--unshare-all", "--uid", "65534", "--gid", "65534",
        "--die-with-parent", "--new-session",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib", "/lib64",
        "--symlink", "usr/bin", "/sbin",
        "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--bind", src, "/work",
        "--chdir", "/work",
        "--clearenv",
        "--setenv", "HOME", "/tmp",
        "--setenv", "PATH", "/usr/bin",
        "--setenv", "PYTHONIOENCODING", "utf-8",
        "--",
        "/usr/bin/timeout", "-s", "KILL", str(int(timeout)),
        "python3", "-I", "-u", "-",
    ]
