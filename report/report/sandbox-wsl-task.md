# Task: WSL-backed sandbox for Windows tool runs

Status: IMPLEMENTED + VERIFIED (2026-10-16, Windows box). Repo code landed:
`backend/sandbox.py` `wsl_probe()`/`wsl_wrap()`/`win_to_wsl()`, `runner.run_python`
`backend=` param with a stdin-fed WSL branch, `backend/main.py` `sandbox_backend`
setting (auto|wsl|off) + boot warm probe, SettingsModal backend select. Harness
14/14 on real WSL (archlinux) + 7/7 failpaths + settings round-trip; full in-app
e2e later with qwen3.5:0.8b (tool block showed uid 65534 / cwd /work / no /mnt /
net blocked / [exit 0]; write-back landed in the active project on Windows).
Acceptance checklist below ticked. Unproven: frozen exe + Linux regression run
only. Full account in `session-log.md` (2026-10-16 close-out).
Update 2026-10-15 (Windows boot probe): WSL2 + Arch distro ARE present; python3
and bwrap are NOT installed in the distro (`sudo pacman -S python bwrap` prepares
the box). Plan of record expanded in fplan.md "v2 ideas" — option sweep done
(AppContainer reads user files, Windows Sandbox is Pro-only + API-less, Docker =
WSL underneath → WSL2 + bwrap chosen). wsl.exe gotcha learned live: stdout is
UTF-16, strip nulls when parsing.
Update 2026-10-16 (discussion + probes, Windows box): READ THIS FIRST —
`sandbox-wsl-plan-update.md` in this folder. It fixes two bugs in the plan
below (the `wsl -e which bwrap` probe in "Design to implement" fails on Arch —
`which` isn't installed; and `find_bwrap()` gates on Linux so `wrap()` argv as
written CANNOT be passed straight to wsl.exe), resolves the plan's
option-(a)/(b) evaluation with live probes (drvfs /mnt/c IS mounted, so the
"home never mounted" framing only holds with the explicit tmpfs; distro has
tar but lacks python3+bwrap; systemd=true), and puts 5 decision points (image
shape, project I/O, first-run UX, cold-boot vs 30s cap, scope) in front of the
user before implementation. No code written yet.

Update 2026-10-16 (later): HANDOFF WRITTEN — `wsl-sandbox-handoff.md`. Distro
now has python+bwrap; a hand-built wsl.exe→bwrap run was PROVEN end-to-end
(net blocked, no /mnt, workdir bind read/write OK). Code not yet written.

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

- [x] Settings: new backend selector round-trips (GET/PATCH), default `auto`
      (verified live: auto→wsl→422(bogus)→off→auto; SettingsModal select added)
- [x] Windows + WSL present + bwrap in distro: tool run executes inside WSL bwrap,
      network blocked, home hidden, scratch writable, output/exit reported correctly
      (harness 14/14 + in-app e2e: uid 65534, cwd /work, no /mnt, minimal root,
      net blocked [Errno 101], exit codes propagate, 30s inner-timeout cap)
- [x] Windows + no WSL / no bwrap: unsandboxed run + loud label + reason logged
      (failpath harness 7/7: mode=unavailable + sandbox_reason with the exact
      one-time install command, shown in the tool block via tool_result_text)
- [ ] Linux: behavior unchanged (bwrap path untouched — regression-test the two
      live checks above: net blocked, home-write no-trace)
      — pending: no Linux box in this session; code path is unchanged (wrap() /
      find_bwrap untouched), needs one regression run
- [x] `sandbox: "wsl"` (or equivalent) visible in the tool block metadata
      (tool block printed uid/cwd/root/net lines; results carry sandbox=wsl/on/
      off/unavailable + reason)
- [x] No hard dependency: Su1ra must never fail to start because WSL/bwrap is absent
      (probe is best-effort, warm probe swallows errors, backend=off just skips)
