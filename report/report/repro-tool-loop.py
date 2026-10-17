"""Repro: build-mode tool loop (ws_ls / ws_edit) through the real /api/chat generator.

Run with APPDATA redirected (the launcher does it) so the user's real DB is untouched.
Stubs ollama.stream_chat with a scripted two-round conversation:
  round 1: model emits tool_calls -> ws_ls
  round 2: model emits text + done
"""
import asyncio, json, os, sys, tempfile, shutil
from pathlib import Path

# Isolation FIRST: fresh APPDATA for this process -> store uses a temp DB
TMP = tempfile.mkdtemp(prefix="su1ra-repro-")
os.environ["APPDATA"] = TMP

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import store  # noqa: E402
store.init_db()
print("DATA_DIR ->", store.DATA_DIR)

import workspace  # noqa: E402

WS = Path(TMP) / "ws"
(WS / "repro-proj").mkdir(parents=True)
(WS / "repro-proj" / "hello.py").write_text("print('hi')\n", encoding="utf-8")
store.set_setting("workspace_root", str(WS))
workspace.set_active_project("repro-proj")

import ollama, main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

calls = {"n": 0}
ROUND_PLAN = []


async def fake_supports_tools(model):
    return True


async def fake_stream_chat(model, messages, system_prompt="", temperature=0.7, num_ctx=0, tools=None, think=None):
    calls["n"] += 1
    rnd = calls["n"]
    roles = [m["role"] for m in messages]
    print(f"--- stub stream_chat round {rnd}: roles={roles} tools={bool(tools)} think={think!r}")
    if rnd == 1:
        name, args = ROUND_PLAN[0]
        yield {"tool_calls": [{"function": {"name": name, "arguments": args}}]}
        yield {"done": True, "eval_count": 5}
    elif rnd == 2:
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        print(f"--- round 2 saw {len(tool_msgs)} tool result(s): {[m['content'][:70] for m in tool_msgs]}")
        yield {"delta": "Here is your directory listing."}
        yield {"done": True, "eval_count": 9}
    else:
        yield {"error": "too many rounds - should not happen"}
        return

ollama.stream_chat = fake_stream_chat
ollama.model_supports_tools = fake_supports_tools
main.ollama.stream_chat = fake_stream_chat

client = TestClient(main.app)

r = client.post("/api/conversations", json={"model": "repro-model", "title": "repro"})
print("create conv:", r.status_code)
CID = r.json()["id"]

CASES = [
    ("ws_ls", {"path": ""}),
    ("ws_ls", {}),                      # missing arg — must not 500
    ("ws_read", {"path": "hello.py"}),
    ("ws_edit", {"path": "hello.py", "find": "hi", "replacement": "hello"}),
    ("ws_write", {"path": "out.txt", "content": "written"}),
    ("ws_mkdir", {"path": "sub"}),
    ("ws_cd", {"project": "other-proj"}),
    ("build_pptx", {"filename": "t.pptx", "theme": "terminal-dark",
                    "slides": [{"layout": "title", "title": "T"}]}),
    ("read_document", {"doc": 1, "offset": 0, "limit": 100}),
    ("nonsense_tool", {}),
]

failures = []
for i, (name, args) in enumerate(CASES):
    print(f"\n########## CASE {name} {args}")
    ROUND_PLAN.clear()
    ROUND_PLAN.append((name, args))
    calls["n"] = 0
    conv_id = CID if i == 0 else CID  # same conversation, history accumulates
    events = []
    try:
        with client.stream("POST", "/api/chat", json={
            "conversation_id": conv_id,
            "content": f"go {name}",
            "model": "repro-model",
            "tools": True,
            "code_mode": True,
            "think": "on",
        }) as resp:
            print("chat status:", resp.status_code)
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    print("UNPARSEABLE:", line[:120])
                    continue
                events.append(obj)
    except Exception as exc:
        print("STREAM DIED:", type(exc).__name__, str(exc)[:200])
        failures.append((name, f"stream died: {exc}"))
        continue
    tool_evts = [e["tool"] for e in events if "tool" in e]
    done = [e for e in events if e.get("done")]
    print("kinds:", [sorted(e.keys())[0] for e in events])
    if not tool_evts:
        failures.append((name, "no tool event"))
        print("!!! NO TOOL EVENT — loop broke before tool result")
        continue
    print("tool output:", tool_evts[0]["output"][:120].replace("\n", " | "))
    if not done:
        failures.append((name, "no done event"))
        print("!!! NO DONE EVENT")
    elif "error" in json.dumps(events).lower() and name != "nonsense_tool":
        pass  # error text inside tool output is fine; error EVENTS checked below
    if any("error" in e and e["error"] for e in events if "error" in e):
        failures.append((name, "error event yielded"))
        print("!!! ERROR EVENT:", [e for e in events if "error" in e])

print("\n========== SUMMARY ==========")
if failures:
    print("FAILURES:")
    for n, why in failures:
        print(" -", n, "->", why)
else:
    print("ALL", len(CASES), "TOOL CASES COMPLETED THE LOOP (tool event + done)")
shutil.rmtree(TMP, ignore_errors=True)
