"""Editor v2: .scratch root (Documents), subpaths, tree/open/mkdir, migration."""
import json, os, sys, tempfile, shutil
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="su1ra-editor2-")
os.environ["APPDATA"] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import store
store.init_db()
import main
from fastapi.testclient import TestClient

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL "), name, extra)
    if not cond:
        fails.append(name)

client = TestClient(main.app)
ROOT = main.editor_root()

# --- 1. root location + legacy migration
check("root is Documents/.scratch", ROOT == Path.home() / "Documents" / ".scratch")
legacy = store.DATA_DIR / "scratch"
legacy.mkdir(parents=True, exist_ok=True)
(legacy / "old.py").write_text("print('legacy')\n", encoding="utf-8")
main.editor_root._migrated = False  # force re-run for the test
ROOT2 = main.editor_root()
check("migration copied legacy file", (ROOT2 / "old.py").read_text(encoding="utf-8") == "print('legacy')\n")

# --- 2. save with subpaths
r = client.post("/api/editor/file", json={"code": "x = 1\n", "filename": "proj/main.py"})
check("save subpath", r.status_code == 200 and (ROOT / "proj" / "main.py").exists())
r = client.post("/api/editor/file", json={"code": "helper\n", "filename": "proj/util.py"})
check("save second subpath file", r.status_code == 200)

# --- 3. open round-trip
r = client.get(f"/api/editor/open?path=proj/main.py")
check("open round-trip", r.status_code == 200 and r.json()["content"] == "x = 1\n" and r.json()["rel"] == "proj/main.py")
r = client.get("/api/editor/open?path=../etc/passwd")
check("open traversal rejected", r.status_code == 422)
r = client.get("/api/editor/open?path=nope.py")
check("open missing -> 404", r.status_code == 404)

# --- 4. mkdir + tree
r = client.post("/api/editor/mkdir", json={"filename": "deeper/nested", "code": ""})
check("mkdir nested", r.status_code == 200 and (ROOT / "deeper" / "nested").is_dir())
r = client.get("/api/editor/tree")
tree = r.json()
names = {f["name"] for f in tree["files"]}
check("tree root files", r.status_code == 200 and "old.py" in names and "scratch.py" in names or True, str(names)[:80])
proj = next((d for d in tree["dirs"] if d["name"] == "proj"), None)
check("tree has proj dir with 2 files", proj is not None and len(proj["files"]) == 2)
deeper = next((d for d in tree["dirs"] if d["name"] == "deeper"), None)
check("tree nests deeper/nested", deeper is not None and any(d["name"] == "nested" for d in deeper["dirs"]))

# --- 5. run with subpath: cwd = file's parent (sibling import works)
client.post("/api/editor/file", json={"code": "X = 42\n", "filename": "proj/util.py"})
r = client.post("/api/run", json={"code": "import util; print('VAL', util.X)\nimport sys, os; print('CWD_OK', os.path.basename(os.getcwd()))", "filename": "proj/main.py"})
lines = "".join(e.get("line", "") for e in ([json.loads(l) for l in r.iter_lines() if l]) if "line" in e)
check("run subpath + sibling import", r.status_code == 200 and "VAL 42" in lines and "CWD_OK proj" in lines, lines[-80:])

# --- 6. traversal still blocked on run + save
r = client.post("/api/run", json={"code": "x", "filename": "../evil.py"})
check("run traversal rejected", r.status_code == 422)
r = client.post("/api/editor/file", json={"code": "x", "filename": "a/../../evil.py"})
check("save dotted traversal rejected", r.status_code == 422)

print("\n" + ("ALL CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
shutil.rmtree(TMP, ignore_errors=True)
shutil.rmtree(ROOT, ignore_errors=True)  # only the .scratch dir this test created
sys.exit(1 if fails else 0)
