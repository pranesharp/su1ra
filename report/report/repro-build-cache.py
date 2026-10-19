"""Verify build-mode prompt-cache optimization:
  1. system prompt is BYTE-STABLE across turns even when project files change
  2. the live listing arrives as a TRAILING context message (fresh each turn)
  3. the KV prefix-cache property: call N's messages[:-1] extends call N-1's
     messages minus ITS trailing context note (the reuse boundary is the tail)
  4. the DB stays clean (no context notes persisted)
  5. chat_payload: keep_alive present, think level mapping, num_ctx passthrough
Run with APPDATA redirected (done below) so the real DB is untouched.
"""
import asyncio, os, sys, tempfile, shutil
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="su1ra-buildopt-")
os.environ["APPDATA"] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import store
store.init_db()

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL "), name, extra)
    if not cond:
        fails.append(name)

from fastapi.testclient import TestClient
import main, ollama, workspace
client = TestClient(main.app)

CTX_MARK = "[context note — auto-attached by the system"

# --- workspace: temp root with a project and one file
root = Path(TMP) / "ws"
proj = root / "proj1"
proj.mkdir(parents=True)
(proj / "a.py").write_text("print('a')\n")
client.patch("/api/settings", json={"workspace_root": str(root)})
client.patch("/api/settings", json={"active_project": "proj1"})

# --- fake stream: capture every call, answer plainly (no tool calls)
calls = []
orig_stream, orig_supports = ollama.stream_chat, ollama.model_supports_tools

async def fake_stream(model, messages, system_prompt="", temperature=0.7, num_ctx=0, tools=None, think=None):
    calls.append({
        "model": model, "messages": messages, "system_prompt": system_prompt,
        "temperature": temperature, "num_ctx": num_ctx, "tools": tools, "think": think,
    })
    yield {"delta": "ok"}

async def fake_supports(model):
    return True

ollama.stream_chat = fake_stream
ollama.model_supports_tools = fake_supports

def send(conv_id, text):
    with client.stream("POST", "/api/chat", json={
        "conversation_id": conv_id, "content": text, "tools": True, "code_mode": True,
    }) as resp:
        body = "".join(resp.iter_text())
    assert '"error"' not in body, body[:300]
    return body

conv = client.post("/api/conversations", json={"model": "test-model", "code_mode": True}).json()

# turn 1
send(conv["id"], "hello")
assert len(calls) == 1, len(calls)
c1 = calls[0]
s1 = c1["system_prompt"]

check("turn1: system has directive, no listing tail",
      "FILE-FIRST DELIVERY" in s1 and CTX_MARK not in s1)
check("turn1: trailing context message present with the listing",
      c1["messages"][-1]["role"] == "user" and CTX_MARK in c1["messages"][-1]["content"]
      and "a.py" in c1["messages"][-1]["content"], repr(c1["messages"][-1]["content"][:60]))
check("turn1: context note is a SEPARATE message after the user msg",
      c1["messages"][-2]["role"] == "user" and c1["messages"][-2]["content"] == "hello"
      and c1["messages"][-2]["content"] not in c1["messages"][-1]["content"])

# turn 2 — a file appears BETWEEN turns (the old code's cache-buster)
(proj / "b.py").write_text("print('b')\n")
send(conv["id"], "now the second turn")
assert len(calls) == 2
c2 = calls[1]

check("turn2: SYSTEM PROMPT BYTE-STABLE (the cache fix)", c2["system_prompt"] == s1)
check("turn2: fresh listing carries b.py",
      "b.py" in c2["messages"][-1]["content"] and CTX_MARK in c2["messages"][-1]["content"])
check("turn2: context notes differ between turns (live data)",
      c2["messages"][-1]["content"] != c1["messages"][-1]["content"])

# KV prefix-cache property: everything of call1 except ITS trailing note is a
# strict prefix of call2's messages
prefix_len = len(c1["messages"]) - 1  # drop turn1's context note
check("cache property: call2 extends call1 (minus the stale tail)",
      c2["messages"][:prefix_len] == c1["messages"][:prefix_len]
      and len(c2["messages"]) > prefix_len)
# ...and the boundary lands exactly on the divergent note (roles/models sane)
check("cache property: divergence is the assistant reply after turn1's note",
      c1["messages"][prefix_len - 1]["role"] == "user"
      and c2["messages"][prefix_len]["role"] == "assistant")

# DB clean: no context notes persisted
msgs = store.get_messages(conv["id"])
check("DB clean: no context notes stored",
      all(CTX_MARK not in (m["content"] or "") for m in msgs),
      f"{[m['role'] for m in msgs]}")

# tools were offered, ctx passed through
check("tools passed to stream_chat", c1["tools"] is not None and len(c1["tools"]) >= 6)
check("num_ctx default passthrough (0 -> no num_ctx)", c1["num_ctx"] == 0)

ollama.stream_chat = orig_stream
ollama.model_supports_tools = orig_supports

# --- chat_payload unit checks (keep_alive + think mapping + num_ctx)
p = ollama.chat_payload("m", [{"role": "user", "content": "x"}], "sys", 0.7, 8192, None, "med")
check("payload: keep_alive 30m", p.get("keep_alive") == "30m", str(p.get("keep_alive")))
check("payload: think med -> medium string", p.get("think") == "medium")
check("payload: num_ctx set", p.get("options", {}).get("num_ctx") == 8192)
p = ollama.chat_payload("m", [{"role": "user", "content": "x"}], "sys", 0.7, 0, None, "off")
check("payload: think off -> False", p.get("think") is False)
check("payload: no num_ctx when 0", "num_ctx" not in p.get("options", {}))
p = ollama.chat_payload("m", [{"role": "user", "content": "x"}], "", 0.7, 0, None, None)
check("payload: no system role when prompt empty",
      all(m["role"] != "system" for m in p["messages"]))
check("payload: no think key when None", "think" not in p)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'ALL PASS' if not fails else f'{len(fails)} FAIL: {fails}'}")
sys.exit(1 if fails else 0)
