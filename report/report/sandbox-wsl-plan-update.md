# WSL bwrap sandbox — plan discussion update (2026-10-16, this Windows box)

Companion to `wsl-sandbox-done.md` (which carries the design of record) and the
fplan.md "v2 ideas" block. This file records what changed after probing the
real machine — including **two bugs found in the existing plan** — and the
decision points that need the user's call before an implementation spec is
locked. No code was written for this. Read together with:
- backend/sandbox.py (find_bwrap, wrap) — the thing on the hot path
- backend/runner.py — run_python + the NEW frozen-aware python_exe() /
  child_spawn_kwargs() from the 2026-10-15 second-window fix (see session-log)

## Probe results (live, this box, 2026-10-16)
- WSL2, default distro **archlinux**, state Stopped → cold-start cost applies.
- `/etc/wsl.conf`: `[boot] systemd=true`. `/mnt` = { c, wsl, wslg }.
- Distro contents: **no bwrap, no python3**, `/usr/sbin/tar` present.
  → the one-time `sudo pacman -S python bwrap` is still the entire prep cost.
- **Bug found in the plan's probe chain:** fplan.md:56 specifies
  `wsl -e which bwrap`. That fails on Arch *even when bwrap is installed*,
  because `which` itself is not in a base Arch image — the execvpe error names
  `which`, not bwrap, and would be misread as "bwrap missing" → permanent
  unsandboxed fallback on any minimal/non-Ubuntu distro.
- **Bug found in the plan's spawn shape:** `find_bwrap()` returns None unless
  PLATFORM == Linux (`__name__ == "nt"` is dead code), so today `wrap()` is
  NEVER CALLED on Windows, so the documented `wsl.exe -e <wrap argv>` can't be
  grafted on. bwrap argv is POSIX-only: `"tmp /home/…"` paths and
  `--die-with-parent` (PR_SET_PDEATHSIG) are meaningless / **hard-fatal** for
  argv[0]=wsl.exe (bwrap parses `C:\Users\…` as a malformed --ro-bind → exit 1
  → the fallback silently kicks in → "implemented, appears broken, blames the
  model").

## Decision 1 — the WSL-side image (what actually runs inside)
Not just "install python3": the model's scripts import numpy/pandas/etc. A
Windows venv can't cross over (Linux binaries inside a Windows venv tree =
confusion). Two viable shapes:
  a) distro python3 + tell model what's available; `pip install` inside WSL on
     demand (needs a plan-approved exception to the no-network policy)
  b) a dedicated docker-style venv/sidecar inside the distro, Su1ra-managed
     requirements.txt (+150–300 MB, ~25–40 min first-time install)
**Default proposed: (a) + "venv-less mode" bwrap profile** — ro-bind only the
real interpreter + its stdlib (`getpath.get_sysroot` / `sys._stdlib_dir`),
tmpfs /home **including /home/\<user\>/.local** (kills Windows' pip --user
cross-contamination class), `--ro-bind /usr /usr` (numpy etc. stay reachable),
**no `--ro-bind /lib` and no `--die-with-parent`** over wsl.exe. Small model
scripts stay dependency-free; heavy imports → tell the model what's allowed.
Needs your call: is (a)-with-no-network the right first increment, or do you
want the sidecar up front?

## Decision 2 — workspace I/O across the boundary (the real risk)
bwrap needs its bind targets to exist **inside the distro fs** (binds from
/mnt/c = 9p, permission quirks, slow: the plan is right to copy in). But a
model that builds a multi-file artifact (a deck's images? an HTML + assets?)
expects to `ws_write` a file, run something, and iterate **on that file** —
and the ws_* tools are on the Windows side, so they'd be writing to a tree the
sandbox never reads and vice versa. Options to choose:
  a) run dir **mirrored both ways** every run — push the ACTIVE PROJECT IN
     (read-only or writable?) alongside the code, pull outputs back after.
     Simple, bounded (projects are small), but "writable project in sandbox"
     weakens containment and pull-back-overwrite can clobber the user's files.
  b) push **code only** (today's shape); anything the script reads must be
     inlined by the model or fetched via ws_read → no file-I/O round trips.
     Containment stays clean; multi-file scripts (model writes data.csv →
     run reads data.csv) are BROKEN unless the model writes and reads within
     one scratch dir.
  c) like (b), but the run's scratch dir IS the project dir mounted writable —
     cleanest for iteration, worst for "home hidden" claims.
**Default proposed: (b) for v1** (matches current behaviour + clean containment),
plus a documented escape: if a script's output is a file, `cat` it or the model
copies it out; revisit with (a) if real decks/HTML+assets workflows complain.
Needs your call — do you want mirror-the-project now?

## Decision 3 — the first-run UX when the distro lacks python3/bwrap
`sudo pacman -S python bwrap` needs a password (non-interactive `wsl -e` can't
sudo without `--user root`). The current "graceful fallback" contract was
written for an env the USER controls; it's actually a ~45–110s first-run.
Options:
  a) fallback-only + label that reads exactly like a task list, e.g.
     `sandbox: off (WSL present — install with: wsl -u root ... ; see /help sandbox)`
  b) `--user root` non-interactive install, run on demand (quiet, no prompts,
     but the app is then responsible for package transactions)
  c) b + a progress UX (stream pacman over NDJSON like ollama_setup does)
**Recommendation: (b) for the install plumbing, but SHIP (a)+(b)-manual first** —
don't take on package-manager responsibility as a side effect of a sandbox
feature; let the OllamaSetup-style callout be the follow-up once the sandbox
itself is proven. Your call.

## Decision 4 — cold-boot latency vs the 30s cap
`wsl -e` on a Stopped distro = distro start + sh + python cold, seconds before
the model's 30s compute even begins. Cap needs to be per-backend
(`runner.TIMEOUT_SECONDS` becomes a function of backend: WSL cap = 30s
**after** interpreter start, i.e. measure spawn → first write), or a background
`wsl.exe -e true` keep-warm ping on app boot when backend=auto/wsl. The plan
has nothing on this. **Recommendation:** measure from spawn-success (code
already knows `t0` at popen — cap logic currently counts from
popen, needs review) + optional keep-warm ping.

## Decision 5 — scope (unchanged from the plan — confirm you still agree)
- `run_python` only. The 4 `build_*` tools (pptx/xlsx/docx/pdf) remain
  in-process on the Windows host — they're Su1ra's own code, not model code.
- editor's run button stays user-initiated + unsandboxed ("the user pressed it").
- Linux bwrap path untouched, regression-tested (net blocked, home no-trace).
- Settings auto-save contract: new `sandbox_backend` select rides the existing
  `commitNow` path; App.jsx reads settings once (line ~457) and threads state,
  so `sandboxTools` needs a sibling `sandboxBackend` — no full plumbing
  rewrite, but the SettingsModal needs the mode-aware prop pattern applied.

## Probe-chain contract (locked regardless of decisions — fixes plan bug)
All POSIX syntax; never via cmd.exe (its `%` expansion vs UTF-16 env dump is an
infinite footgun); decode UTF-16 (utf-16-le → utf-8 fallback) with nulls
stripped; all output matched ASCII-only; **one** combined round-trip:
```
wsl.exe -l -q                                   ASCII-guarded → distro list
wsl.exe -e sh -c 'command -v bwrap; command -v python3; ...'   exit 127-safe
```
then `wsl.exe --list --all` gated behind `--status >= 2` (it prints an
English-only usage block to stderr with zero distros). Cache per (backend,
distro, minutes-since-WSL-service-change), invalidate on toggle; probes run in
a ThreadPoolExecutor off the request path (they block 1–5s on cold start);
failures cached short. **Never** `--shutdown` or `--manage`-write without user
action; **always** explicit `-d <distro>` once 2+ distros exist.

## Implementation shape (for the real build, after decisions)
1. `sandbox.py`: new `wrap_profile` concept (full | venvless) + WSL argv
   builder producing POSIX-only args; `find_bwrap()` platform gate fixed;
   WSL probe module (the chain above).
2. `runner.py`: `run_python(code, sandboxed, cwd)` gains backend branch →
   `wsl_sandbox.py` (new file) owns: copy-in → wsl.exe -e bwrap … → stream
   stdout/stderr → copy-out; per-backend timeout.
3. `main.py`: `sandbox_backend` in GET/PATCH settings (validated enum);
   dispatch passes backend; ws_cd still updates the dir the copy uses.
4. `frontend`: SettingsModal select + `sandbox: "wsl"` label + the
   task-list-style off message in ChatView (one string change — it's plain
   content, not per-state). No App.jsx stream-routing change needed.
5. Docs: AGENTS.md section + README note + release-notes line ("model code
   runs in WSL+bubblewrap on Windows; needs a one-time distro install").
6. Tests: probe-chain unit tests w/ mocked wsl.exe (UTF-16 fixtures, the `--`
   arg case, the which-missing case) + fake-wsl shim script (logs argv, returns
   canned outputs). Real-box checklist = the 6 acceptance items in
   wsl-sandbox-done.md + the two Windows-only caveats (exit code via
   `$?`-echo-then-sudo-true; UTF-16 console reads must never be assumed —
   wsl.exe → appends NULs to the child's UTF-8).

## Unverified / must-do on the real box
- bwrap actually runs inside this Arch-WSL (unprivileged userns under 9p +
  WSL's kernel config) — plan asserts it; not yet proven even with it installed.
- wsl.exe `-e` arg pass-through vs `-- <cmdline>` string splitting.
- stdout encoding behaviour when the inner process writes pure UTF-8.
- the 5 s cold-start cost, and whether keep-warm is needed at all.
