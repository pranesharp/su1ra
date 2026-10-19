"""Verify chat naming: derived first-message titles, AI auto-title endpoint,
and manual-rename priority (titled_manually). The LLM call is monkeypatched —
no ollama needed. Run with APPDATA redirected (done below) so the real DB is
untouched.
"""
import asyncio, os, sys, tempfile, shutil
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="su1ra-naming-")
os.environ["APPDATA"] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import store
store.init_db()

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL "), name, extra)
    if not cond:
        fails.append(name)

# --- 1. derive_title: single line, collapsed, capped
import main
check("multiline collapsed", main.derive_title("hi\n\nthere  friend") == "hi there friend", repr(main.derive_title("hi\n\nthere  friend")))
check("capped at 48", len(main.derive_title("x" * 200)) == 48)
check("empty safe", main.derive_title("") == "" and main.derive_title(None) == "")

# --- 2. _clean_llm_title: wrappers, labels, quotes, first line
cases = [
    ('"Adjacency Matrices"', "Adjacency Matrices"),
    ("Title: Binary Search Tree", "Binary Search Tree"),
    ("<think>hmm let me think</think>\nWSL bwrap Sandbox", "WSL bwrap Sandbox"),
    ("<think>never closed...", ""),  # unclosed think swallows the line
    ("First line\nsecond line", "First line"),
    ("  spaced   out  ", "spaced out"),
]
for raw, want in cases:
    got = main._clean_llm_title(raw)
    check(f"clean({raw[:24]!r})", got == want, f"-> {got!r} want {want!r}")

# --- 3. endpoint: AI title wins over derived, fallback on failure
from fastapi.testclient import TestClient
import main as M
client = TestClient(M.app)

conv = client.post("/api/conversations", json={"model": "m"}).json()
store.add_message(conv["id"], "user", "how do I parse yaml in python")
store.add_message(conv["id"], "assistant", "Use PyYAML: yaml.safe_load(text).")

async def fake_ai(model, user_text, assistant_text):
    # contract: generate_chat_title returns the CLEANED title (the real one
    # runs _clean_llm_title internally — that path is unit-tested above)
    return "YAML Parsing in Python"
orig = M.generate_chat_title
M.generate_chat_title = fake_ai
resp = client.post(f"/api/conversations/{conv['id']}/auto-title")
r = resp.json()
check("ai title applied", r.get("title") == "YAML Parsing in Python" and r.get("source") == "ai", str(r))
check("ai title persisted", store.get_conversation(conv["id"])["title"] == "YAML Parsing in Python")

# --- 4. fallback: LLM returns None -> derived from first user message
conv2 = client.post("/api/conversations", json={"model": "m"}).json()
store.add_message(conv2["id"], "user", "explain   ctypes\narrays please")
store.add_message(conv2["id"], "assistant", "ctypes arrays are fixed-size C arrays.")
async def _none_async(*a, **k):
    return None
M.generate_chat_title = _none_async
r = client.post(f"/api/conversations/{conv2['id']}/auto-title").json()
check("fallback derived", r.get("title") == "explain ctypes arrays please" and r.get("source") == "derived", str(r))

# --- 5. manual rename wins (and freezes)
client.patch(f"/api/conversations/{conv2['id']}", json={"title": "My ctypes Notes"})
check("manual flag set", store.get_conversation(conv2["id"])["titled_manually"] is True or store.get_conversation(conv2["id"])["titled_manually"] == 1)
M.generate_chat_title = fake_ai
r = client.post(f"/api/conversations/{conv2['id']}/auto-title").json()
check("manual title kept", r.get("source") == "kept" and r.get("title") == "My ctypes Notes", str(r))

# --- 6. no exchange yet -> kept
conv3 = client.post("/api/conversations", json={"model": "m"}).json()
r = client.post(f"/api/conversations/{conv3['id']}/auto-title").json()
check("empty chat kept", r.get("source") == "kept")

# --- 7. /clear wipes title AND the manual freeze
client.patch(f"/api/conversations/{conv3['id']}", json={"title": "temp"})
client.post(f"/api/conversations/{conv3['id']}/clear")
row = store.get_conversation(conv3["id"])
check("clear resets title+flag", row["title"] == "" and not row["titled_manually"])

# --- 8. tool/labelled messages don't count as the first assistant answer
conv4 = client.post("/api/conversations", json={"model": "m"}).json()
store.add_message(conv4["id"], "assistant", "")  # empty assistant row (aborted stream)
r = client.post(f"/api/conversations/{conv4['id']}/auto-title").json()
check("empty assistant -> kept", r.get("source") == "kept")

M.generate_chat_title = orig
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAIL: {fails}'}")
sys.exit(1 if fails else 0)
