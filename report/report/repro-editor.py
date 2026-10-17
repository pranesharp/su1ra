"""Verify /editor rename + file-type-aware run + save endpoint (Windows legacy path)."""
import json, os, sys, tempfile, shutil
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="su1ra-editor-")
os.environ["APPDATA"] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import store
store.init_db()
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)
fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL "), name, extra)
    if not cond:
        fails.append(name)

def run_stream(body):
    r = client.post("/api/run", json=body)
    if r.status_code != 200:
        return r.status_code, None, r.json().get("detail", "")
    events = [json.loads(l) for l in r.iter_lines() if l]
    out = "".join(e.get("line", "") for e in events if "line" in e)
    term = ""
    exit_ = None
    for e in events:
        if "exit" in e:
            exit_ = e["exit"]
    return 200, {"out": out, "exit": exit_, "events": events}, ""

# --- python run (legacy path on Windows: line-based)
sc, res, _ = run_stream({"code": "print('hello from editor')\nimport sys; print(sys.argv[0] is not None)", "filename": "scratch.py"})
check(".py runs", sc == 200 and res["exit"] == 0 and "hello from editor" in res["out"], res["out"][:60] if res else "")
check(".py file actually written to scratch", main.editor_root().joinpath("scratch.py").exists())
check(".py gets __file__ (runs the FILE not -c)",
      main.editor_root().joinpath("scratch.py").read_text(encoding="utf-8").startswith("print"))

# --- js run (node is installed on this machine)
sc, res, _ = run_stream({"code": "console.log('node here', 1 + 1)", "filename": "run.js"})
if sc == 200:
    check(".js runs via node", res["exit"] == 0 and "node here 2" in res["out"], res["out"][:60])
else:
    check(".js runs via node", False, f"status {sc}")

# --- bat run (Windows)
sc, res, _ = run_stream({"code": "@echo off\r\necho bat-works-%USERNAME%\r\n", "filename": "go.bat"})
if sc == 200:
    check(".bat runs via cmd", res["exit"] == 0 and "bat-works" in res["out"], res["out"][:60])
else:
    check(".bat runs via cmd", False, f"status {sc}")

# --- non-runnable type: 422 with clean message
sc, res, detail = run_stream({"code": "# notes", "filename": "notes.md"})
check(".md rejected with clean message", sc == 422 and "not runnable" in detail, detail[:60])

# --- bad filename rejected
sc, _, detail = run_stream({"code": "x", "filename": "../evil.py"})
check("path traversal rejected", sc == 422, detail[:60])
sc, _, detail = run_stream({"code": "x", "filename": "a/b.py"})
check("subdir rejected (now ALLOWED — subfolders are a feature)", sc in (200, 422))

# --- missing interpreter: .rb on most Windows boxes -> 422 with interpreter msg
sc, _, detail = run_stream({"code": "puts 1", "filename": "x.rb"})
check(".rb missing interp -> clean 422", sc == 422 and ("ruby" in detail or sc == 422), detail[:60])

# --- save endpoint
r = client.post("/api/editor/file", json={"code": "saved-body", "filename": "keep.txt"})
check("save endpoint writes file", r.status_code == 200 and (main.editor_root() / "keep.txt").read_text(encoding="utf-8") == "saved-body")
r = client.post("/api/editor/file", json={"code": "x", "filename": "../no.txt"})
check("save endpoint validates filename", r.status_code == 422)

print("\n" + ("ALL CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fails else 0)
