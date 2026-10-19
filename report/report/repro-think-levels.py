"""Verify think levels (off/low/medium/high/on) end-to-end.

Covers: normalize_think aliases, /api/settings round-trip for the two loadout
think defaults, per-chat think persistence, and build_history's think strip
(closed block, unclosed tail, mid-code survivor). Run with APPDATA redirected
(done below) so the real DB is untouched.
"""
import json, os, sys, tempfile, shutil
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="su1ra-thinklv-")
os.environ["APPDATA"] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import store
store.init_db()

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL "), name, extra)
    if not cond:
        fails.append(name)

# --- 1. normalize_think: levels + aliases
cases = [
    ("off", "off"), ("low", "low"), ("med", "medium"), ("medium", "medium"),
    ("high", "high"), ("ultra", "on"), ("on", "on"), ("max", "on"),
    ("TRUE", "on"), ("0", "off"), ("auto", None), ("", None), ("DEFAULT", None),
]
for raw, want in cases:
    got = store.normalize_think(raw)
    check(f"normalize_think({raw!r})", got == want, f"-> {got!r} want {want!r}")
try:
    store.normalize_think("banana")
    check("normalize_think junk raises", False)
except ValueError:
    check("normalize_think junk raises", True)

# legacy DB values stay valid (old rows hold on/off/None only)
for legacy in ("on", "off"):
    check(f"legacy value {legacy!r} accepted", store.normalize_think(legacy) == legacy)

# --- 2. ollama.normalize_think_param: payload shape
import ollama
pcases = [
    (None, None), (True, True), (False, False), ("off", False),
    ("on", True), ("ultra", True), ("max", True), ("med", "medium"),
    ("low", "low"), ("medium", "medium"), ("high", "high"), ("auto", None),
    ("", None),
]
for raw, want in pcases:
    got = ollama.normalize_think_param(raw)
    check(f"think_param({raw!r})", got == want, f"-> {got!r} want {want!r}")

# --- 3. settings round-trip (GET/PATCH) for both loadout defaults
from fastapi.testclient import TestClient
import main
client = TestClient(main.app)

r = client.patch("/api/settings", json={"loadout_code_think": "med"})
check("PATCH loadout_code_think=med", r.status_code == 200, r.text[:120])
r = client.get("/api/settings")
check("GET loadout_code_think canonical", r.json().get("loadout_code_think") == "medium",
      f"-> {r.json().get('loadout_code_think')!r}")
r = client.patch("/api/settings", json={"loadout_casual_think": "high"})
check("PATCH loadout_casual_think=high (levels now legal)", r.status_code == 200)
r = client.get("/api/settings")
check("GET loadout_casual_think", r.json().get("loadout_casual_think") == "high")
r = client.patch("/api/settings", json={"loadout_code_think": "banana"})
check("PATCH junk level -> 422", r.status_code == 422)
r = client.patch("/api/settings", json={"loadout_code_think": "auto"})
check("PATCH auto accepted", r.status_code == 200)
r = client.get("/api/settings")
check("auto cleared to empty", r.json().get("loadout_code_think") == "")

# --- 4. per-chat think persistence with a level
conv = client.post("/api/conversations", json={"model": "m", "think": "medium"}).json()
check("create chat think=medium", conv.get("think") == "medium")
conv2 = client.post("/api/conversations", json={"model": "m", "think": "ultra"}).json()
check("create chat think=ultra -> on", conv2.get("think") == "on")
upd = client.patch(f"/api/conversations/{conv['id']}", json={"think": "off"}).json()
check("update chat think=off", upd.get("think") == "off")

# --- 5. build_history strips reasoning from outgoing history
h = main.build_history([
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "<think>\nlong reasoning here\nmore\n</think>\n\nThe answer."},
    {"role": "user", "content": "next"},
])
check("closed think block stripped", h[1]["content"] == "The answer.", repr(h[1]["content"]))
h = main.build_history([
    {"role": "assistant", "content": "<think>\ndied mid-stream with no closer"},
])
check("unclosed think tail stripped", h[0]["content"] == "", repr(h[0]["content"]))
h = main.build_history([
    {"role": "assistant", "content": "<think>x</think>\n\n```html\n<think> inside code\n```"},
])
check("mid-code <think> survives (leading-only strip)", "inside code" in h[0]["content"], repr(h[0]["content"]))
h = main.build_history([
    {"role": "assistant", "content": "<think>a</think> mid <think>b</think> tail"},
])
check("non-leading block kept, leading stripped", h[0]["content"] == "mid <think>b</think> tail", repr(h[0]["content"]))
h = main.build_history([
    {"role": "assistant", "content": "<think>r</think>", "tool_calls": [{"function": {"name": "ws_ls", "arguments": {}}}]},
])
check("tool_calls preserved through strip", h[0].get("tool_calls") is not None and h[0]["content"] == "")
h = main.build_history([{"role": "assistant", "content": "plain answer"}])
check("plain content untouched", h[0]["content"] == "plain answer")

# --- 5. prompt-based effort guidance (bool-only model lever)
e = main.apply_think_effort("BASE", "low")
check("low appends guidance", e.startswith("BASE") and "Reasoning effort is set to low" in e, repr(e[-40:]))
e = main.apply_think_effort("BASE", "high")
check("high appends guidance", "Reasoning effort is set to high" in e)
e = main.apply_think_effort("BASE", "med")
check("med alias reaches medium (no injection)", e == "BASE", repr(e))
for keep in ("medium", "off", "on", "ultra", None, "auto", "", "banana"):
    e = main.apply_think_effort("BASE", keep)
    check(f"no injection for {keep!r}", e == "BASE", repr(e))
e = main.apply_think_effort("", "low")
check("empty sysprompt -> guidance only", e.startswith("Reasoning effort is set to low"), repr(e[:40]))
e = main.apply_think_effort("", True)
check("bool True -> no injection", e == "")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAIL: {fails}'}")
sys.exit(1 if fails else 0)
