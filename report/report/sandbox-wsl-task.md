# Task: WSL-backed sandbox for Windows tool runs

Status: QUEUED (not started — nothing exists in the repo for this yet; verified
2026-10-13 from this Linux clone: `backend/sandbox.py` is Linux-bwrap only, no WSL
code in any commit local or remote, fplan checkbox unchecked).

## Why

`run_python` tool runs are sandboxed on Linux via bubblewrap (no network, home
hidden under tmpfs, read-only root, only the run dir writable). On Windows the
sandbox is unavailable and tool runs execute unsandboxed with only the loud
`sandbox: unavailable` label + runner caps (30s timeout, output caps, kill on
disconnect). Goal: give Windows the same containment by routing tool runs through
WSL, where bwrap is available.

## Current architecture (what the implementation must plug into)

- `backend/sandbox.py`:
  - `find_bwrap()` → returns None unless `platform.system() == "Linux"`
  - `wrap(cmd, writable_dir, ro_dirs=())` → full bwrap argv (unshare-net/pid/ipc,
    die-with-parent, new-session, dev/proc/tmpfs, ro-bind /, tmpfs over home,
    ro-binds for the venv, bind for the writable dir) or None
- `backend/runner.py` → `run_python(code, sandboxed=True, cwd=None)`:
  - if sandboxed: `wrapped = sandbox.wrap(cmd, workdir, ro_dirs=[interpreter_root()])`
  - runs the returned argv; result dict shape: `{exit, output, timed_out, capped,
    sandbox}` where `sandbox` is `"on"` / `"off"` (off = loud fallback)
- Settings toggle: `sandbox_tools` (default on) — user can disable sandboxing.
- Verified live on Linux (2026-10-13): sandboxed run computes, network connect
  raises OSError inside, home-dir write leaves no trace on real disk.

## Design to implement (agreed direction, details open)

1. **Mode setting**: `sandbox_backend` ∈ {`auto`, `bwrap`, `wsl`, `off`} in settings
   (default `auto` = bwrap on Linux, WSL on Windows if available, else unsandboxed).
   Surface it in SettingsModal next to the existing sandbox toggle.
2. **WSL path (Windows only)**: when mode resolves to `wsl`, build the command as
   `wsl.exe -e <bwrap argv…>` with paths translated:
   - code + scratch dir must live somewhere WSL can reach. Two options to evaluate:
     (a) `/mnt/…` drvfs path for the writable dir (slow + 9p permission quirks) vs
     (b) copy code into the WSL filesystem (`~/.su1ra_sandbox/<run>/`), run there,
        copy output/exit back — fast, fully inside WSL, no drvfs quirks. Recommend (b).
   - The interpreter: the Windows venv's python.exe CANNOT run inside WSL. The WSL
     side needs its own python3 (prompt WSL user to `sudo apt install python3` on
     first use, or detect and report missing clearly). This is the main new failure
     mode to design for.
   - find_bwrap must probe INSIDE wsl (`wsl.exe -e which bwrap`) — bwrap may need
     `wsl --install` + `sudo apt install bubblewrap` on first use; treat missing
     pieces as a graceful fallback to "unsandboxed + loud label", never a crash.
3. **Fallback contract** (unchanged): when the chosen backend is missing/broken →
   run unsandboxed, label it in the tool block, log the reason. Never silently
   pretend containment happened.
4. **Testing from Linux**: detection order, settings round-trip, and fallback
   labeling are testable here. The WSL execution path itself is only truly
   verifiable on the Windows machine (needs `wsl --install` + a distro).

## Acceptance checklist (for whichever agent picks this up)

- [ ] Settings: new backend selector round-trips (GET/PATCH), default `auto`
- [ ] Windows + WSL present + bwrap in distro: tool run executes inside WSL bwrap,
      network blocked, home hidden, scratch writable, output/exit reported correctly
- [ ] Windows + no WSL / no bwrap: unsandboxed run + loud label + reason logged
- [ ] Linux: behavior unchanged (bwrap path untouched — regression-test the two
      live checks above: net blocked, home-write no-trace)
- [ ] `sandbox: "wsl"` (or equivalent) visible in the tool block metadata
- [ ] No hard dependency: Su1ra must never fail to start because WSL/bwrap is absent
