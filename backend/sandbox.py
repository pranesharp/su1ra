import os
import platform
import shutil


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
