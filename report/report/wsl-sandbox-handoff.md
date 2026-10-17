# WSL sandbox — HANDOFF (2026-10-16) — START HERE in the new session

Read order: this file → `sandbox-wsl-plan-update.md` (decisions/background) →
`wsl-sandbox-done.md` (acceptance checklist). Code to touch: `backend/sandbox.py`,
`backend/runner.py`, `backend/main.py` (settings + run_python dispatch),
`frontend/src/components/SettingsModal.jsx`.

## Status: PROVEN by hand, NOT yet implemented in code
No repo code was changed for WSL in this session. What changed is the machine
and the evidence:

1. **Distro prepared (this box).** `archlinux` (WSL2, kernel
   6.18.54.1-microsoft-standard-WSL2) now has `python 3.14.8` + `bubblewrap 0.13.1`.
   - Gotcha: plain `pacman -S python bubblewrap` FAILED (stale db → 404 on .sig).
     Working command (non-interactive, no password because `-u root`):
     `wsl.exe -d archlinux -u root -e sh -c 'pacman -Syu --needed --noconfirm python bubblewrap'`
   - Default WSL user on this box is already root (uid 0).
   - Binaries live at `/usr/sbin/bwrap`, `/usr/sbin/python3` (Arch merged-usr;
     `/usr/bin/python3` also works). Use `command -v`, never `which` (absent on Arch).

2. **End-to-end sandbox run WORKS.** Exact command (run from Windows):
   ```
   wsl.exe -d archlinux -u root --cd / -e bwrap \
     --unshare-all --uid 65534 --gid 65534 --die-with-parent --new-session \
     --ro-bind /usr /usr --symlink usr/bin /bin --symlink usr/lib /lib \
     --symlink usr/lib /lib64 --symlink usr/bin /sbin \
     --dev /dev --proc /proc --tmpfs /tmp \
     --bind /mnt/c/Users/prane/AppData/Local/Temp/sbx /work --chdir /work \
     --clearenv --setenv HOME /tmp --setenv PATH /usr/bin --setenv PYTHONIOENCODING utf-8 \
     -- /usr/bin/timeout -s KILL 30 python3 -I -u -     < script.py
   ```
   Result (exit 0):
   - runs as uid 65534 (nobody), python 3.14.8, cwd /work
   - READ a file written from Windows into the bound dir ✓
   - WROTE out.txt inside → visible on the Windows side ✓ (drvfs bind works
     inside bwrap — the plan-update feared 9p quirks; none hit for read/write)
   - `/` contains only bin dev lib lib64 proc sbin tmp usr work → **no /mnt,
     Windows drive invisible**, no /home, no /etc ✓
   - network: `Errno 101 Network is unreachable` ✓
   - code passed on **stdin** (`python3 -I -u -`) → no quoting/escaping of model
     code through wsl.exe argv at all. KEEP THIS.
   - `--die-with-parent` did NOT break anything (plan-update worried it would).
   - Output came back clean UTF-8 when redirected (the UTF-16 issue is only
     wsl.exe's OWN messages, e.g. `wsl -l`; still strip `\0` defensively).
   - Windows path → WSL path: `wsl.exe -e wslpath -a 'C:\...'` (or compute
     `/mnt/<drive lower>/<rest with />` directly — cheaper, no extra spawn).

## Recommended implementation (resolves plan-update decisions with evidence)
- **Decision 2 (project I/O): bind the run's workdir (active project dir or
  `.scratch`) read-write at `/work`.** Proven above; nothing else of Windows is
  visible. This keeps the ws_write → run_python → read-file loop working with
  zero copy-in/copy-out code. (Plan-update default was code-only; this is
  strictly better now that drvfs-in-bwrap is proven.) Confirm with user.
- **Decision 1 (image): distro python3 only, no pip, no network** for v1.
  Tell the model in the tool description: "stdlib only in the sandbox".
- **Decision 3 (first run): detect + label, plus an explicit button later.**
  When probe fails, tool result text = exact fix command (the `-Syu` line above).
  Do NOT auto-run pacman from a tool call.
- **Decision 4 (cold start):** distro was `Stopped`; first `wsl.exe` call costs
  seconds. Do one background warm probe at backend startup when backend
  resolves to wsl (off the request path, `asyncio.to_thread`). Keep the
  30s cap INSIDE (`timeout -s KILL 30`) and give the outer Windows-side
  `wait_for` a looser cap (e.g. 45s) so cold boot isn't counted against the model.
- **Decision 5 (scope):** run_python only; editor run stays unsandboxed; Linux
  bwrap path untouched.

## Code plan (small — ~150 lines)
1. `backend/sandbox.py`
   - keep `find_bwrap()`/`wrap()` for Linux as-is.
   - add `wsl_probe()` (cached; ~10 min ok-cache, 60s fail-cache): run
     `wsl.exe -e sh -c 'command -v bwrap && command -v python3'` with
     `runner.child_spawn_kwargs()` (CREATE_NO_WINDOW!) + timeout 20s; return
     `{ok, reason, distro}`; any exception → ok False. No WSL installed →
     `FileNotFoundError` → reason "WSL not installed".
   - add `wsl_wrap(workdir)` → argv list exactly as above, with
     `win_to_wsl(workdir)` for the bind source. Code goes via stdin, so the
     argv ends `python3 -I -u -`.
2. `backend/runner.py` `run_python(code, sandboxed, cwd, backend="auto")`
   - resolve: linux→bwrap (existing); nt + auto/wsl + probe ok → wsl; else off.
   - wsl branch: spawn argv with `stdin=PIPE`, write `code.encode()`, close stdin,
     then reuse the existing reader/caps loop unchanged. `mode = "wsl"`.
   - IMPORTANT: the wsl branch must NOT require a Windows python (skip the
     `python_exe()` / `no_python` early return when backend is wsl).
   - unavailable → `mode = "unavailable"` + append probe reason to output.
3. `backend/main.py`: setting `sandbox_backend` ∈ auto|wsl|off (default auto),
   GET/PATCH validated like other enums; pass to run_python; warm probe in the
   startup event (next to `start_sysmon()`).
4. Frontend: SettingsModal select next to the sandbox toggle (commitNow path);
   tool block already shows `sandbox:` field — verify "wsl" renders.
5. AGENTS.md: replace "Windows tool runs unsandboxed" notes; add the pacman
   `-Syu` gotcha and the stdin-code rule.

## Verification checklist for the new session
- [ ] `python -c` harness calling `runner.run_python` with backend wsl: print,
      net blocked, `os.listdir('/')` has no mnt, file write lands in workdir,
      exit code propagates (`sys.exit(3)` → exit 3), infinite loop killed ~30s.
- [ ] WSL absent simulation (monkeypatch probe ok=False) → unavailable label + fix text.
- [ ] Live in the app: /build chat, ask model to run_python → tool block shows
      `sandbox: wsl`, NO second Su1ra window, no console flash.
- [ ] Linux regression (later, on Arch box): bwrap path unchanged.

## Other things worth pointing out (from this session's review)
- The second-window fix (runner `python_exe()` / `is_app_exe` / Store alias /
  `CREATE_NO_WINDOW`) reads correct; nothing broken spotted. Still only verified
  under a SIMULATED frozen env — rebuild the installer and test the real exe.
  With the wsl backend, run_python stops depending on a Windows python at all,
  which removes that whole failure class for sandboxed runs.
- `git status` shows `packaging/output/Su1ra-setup-x64.exe` DELETED and an
  untracked `Su1ra-setup-x64_v0.3.2.exe` — if the landing page links
  `releases/latest/download/Su1ra-setup-x64.exe`, the release asset must keep
  the un-versioned name. Intentional? Decide before committing.
- `desktop.py` still has no single-instance guard (open item in AGENTS.md).
- Leftover test dir: `C:\Users\prane\AppData\Local\Temp\sbx` (data.txt, out.txt) — safe to delete.
