"""Verify per-mode system prompts + per-chat code_mode persistence.

Run with APPDATA redirected (done below) so the real DB is untouched.
"""
import json, os, sys, tempfile, shutil
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="su1ra-modesys-")
os.environ["APPDATA"] = TMP
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import store
store.init_db()

fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL "), name, extra)
    if not cond:
        fails.append(name)

# --- 1. casual default ships empty; build default seeded from sysp.txt
casual = store.get_setting("default_system_prompt_casual") or ""
build = store.get_setting("default_system_prompt") or ""
check("casual default empty", casual == "")
check("build default = sysp.txt", build.strip().startswith("# SYSTEM PROMPT"), f"({len(build)} chars)")

# --- 2. normalization: stamped prompts cleared, customs kept, tool-msg chats backfilled
store.set_setting("default_system_prompt_bundled", "OLD-MARKER")
c_stamp_old = store.create_conversation(title="stamped-old", system_prompt="OLD-MARKER")
c_stamp_new = store.create_conversation(title="stamped-new", system_prompt=build)
c_custom = store.create_conversation(title="custom", system_prompt="MY CUSTOM PROMPT")
c_tool = store.create_conversation(title="had-tools")
store.add_message(c_tool["id"], "tool", "[tool output]")
# the normalization already ran on the first init_db (fresh DB) — drop its
# guard row entirely so the second run processes the rows we just stamped
import sqlite3 as _sq
_c = _sq.connect(store.DB_PATH)
_c.execute("DELETE FROM settings WHERE key = 'perchat_sysp_norm'")
_c.commit()
_c.close()
store.init_db()
for c, expect_cleared in [(c_stamp_old, True), (c_stamp_new, True), (c_custom, False)]:
    row = store.get_conversation(c["id"])
    check(f"normalization: {c['title']}" + (" cleared" if expect_cleared else " kept"),
          (row["system_prompt"] == "") == expect_cleared)
row = store.get_conversation(c_tool["id"])
check("backfill: tool-msg chat -> build", row["code_mode"] is True)

# --- 3. create/update persist code_mode
c_casual = store.create_conversation(title="cas-chat")
c_build = store.create_conversation(title="bld-chat", code_mode=True)
check("create casual code_mode=False", store.get_conversation(c_casual["id"])["code_mode"] is False)
check("create build code_mode=True", store.get_conversation(c_build["id"])["code_mode"] is True)
store.update_conversation(c_casual["id"], code_mode=True)
check("update code_mode persists", store.get_conversation(c_casual["id"])["code_mode"] is True)
store.update_conversation(c_casual["id"], code_mode=False)
check("update code_mode False persists", store.get_conversation(c_casual["id"])["code_mode"] is False)

# --- 4. chat(): per-mode prompt resolution
import ollama, main
from fastapi.testclient import TestClient

captured = {}
async def fake_supports_tools(model):
    return True

async def fake_stream_chat(model, messages, system_prompt="", *args, **kw):
    # main.py passes sys_prompt as 3rd positional; ollama.stream_chat is what
    # turns it into the {"role":"system"} payload message — so assert HERE.
    captured["system"] = (system_prompt or "").strip()
    yield {"delta": "ok"}
    yield {"done": True, "eval_count": 1}

ollama.stream_chat = fake_stream_chat
ollama.model_supports_tools = fake_supports_tools
main.ollama.stream_chat = fake_stream_chat
main.ollama.model_supports_tools = fake_supports_tools
client = TestClient(main.app)

def chat(conv_id, code_mode):
    captured.clear()
    r = client.post("/api/chat", json={
        "conversation_id": conv_id, "content": "hi", "model": "m",
        "tools": code_mode, "code_mode": code_mode, "think": "off",
    })
    assert r.status_code == 200, r.text
    for line in r.iter_lines():
        if line:
            json.loads(line)

# build chat, no override -> sysp.txt injected
chat(c_build["id"], True)
check("build sends sysp as system role", captured["system"].startswith("# SYSTEM PROMPT"))
# casual chat, no override, casual default empty -> NO system message
chat(c_casual["id"], False)
check("casual (empty default) sends no system", captured["system"] == "")
# casual default set -> injected
store.set_setting("default_system_prompt_casual", "CASUAL PERSONA")
chat(c_casual["id"], False)
check("casual (set default) sends it", captured["system"] == "CASUAL PERSONA")
# build default does not leak into casual
store.set_setting("default_system_prompt_casual", "")
chat(c_casual["id"], False)
check("build default does not leak into casual", captured["system"] == "")
# per-chat override wins in casual
store.update_conversation(c_casual["id"], system_prompt="MY CHAT PROMPT")
chat(c_casual["id"], False)
check("per-chat override wins in casual", captured["system"] == "MY CHAT PROMPT")
# per-chat override wins in build
store.update_conversation(c_build["id"], system_prompt="BUILD CHAT OVERRIDE")
chat(c_build["id"], True)
# build mode appends the workspace/tool directive + project context after it
check("per-chat override wins in build", captured["system"].startswith("BUILD CHAT OVERRIDE"))

# --- 5. API models accept the fields
r = client.post("/api/conversations", json={"model": "m", "code_mode": True})
check("POST /api/conversations code_mode", r.status_code == 200 and r.json()["code_mode"] is True)
r = client.patch(f"/api/conversations/{r.json()['id']}", json={"code_mode": False})
check("PATCH code_mode", r.status_code == 200 and r.json()["code_mode"] is False)
r = client.get("/api/settings")
check("GET /api/settings has casual default", "default_system_prompt_casual" in r.json())

print("\n" + ("ALL CHECKS PASSED" if not fails else f"FAILURES: {fails}"))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fails else 0)
