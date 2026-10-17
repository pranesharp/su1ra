"""Repro: request_resources tool + resource cart endpoints (RAG ground-truth loop).

Run with APPDATA redirected (the launcher does it) so the user's real DB is untouched.
Stubs ollama.stream_chat with a scripted conversation (round 1 emits the
request_resources tool call), and runs a tiny local HTTP stub that serves:
  - a fetchable page   (for the cart's raw/summarize fetch)
  - a non-streaming /api/chat  (for the summarize-mode one-shot)

Flow mirrors the real loop:
  chat#1: model -> request_resources -> STOP
  cart send: pages stored as kind="document" attachments (raw + summarize + errors)
  chat#2: synthetic user message carries [doc 1][doc 2]; model read_document(doc=1)
  second batch: numbering must CONTINUE at [doc 3] (the per-message restart fix)
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Isolation FIRST: fresh APPDATA for this process -> store uses a temp DB
TMP = tempfile.mkdtemp(prefix="su1ra-repro-cart-")
os.environ["APPDATA"] = TMP

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import store  # noqa: E402
store.init_db()
print("DATA_DIR ->", store.DATA_DIR)

import main  # noqa: E402
import ollama  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# --- local HTTP stub: one page + one non-streaming ollama chat ---------------

PAGE_HTML = """<html><head><title>OpenProcess</title></head><body>
<h1>OpenProcess function (processthreadsapi.h)</h1>
<p>HANDLE OpenProcess(DWORD dwDesiredAccess, BOOL bInheritHandle, DWORD dwProcessId);</p>
<p>PROCESS_ALL_ACCESS = 0x001F0FFF. dwDesiredAccess must be a valid access right.</p>
</body></html>"""

STUB = {}


def _stub_handler(handler_cls):
    class H(handler_cls):
        def do_GET(self):
            if self.path == "/page":
                body = PAGE_HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/api/chat":
                n = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(n) or b"{}")
                STUB["last_chat_payload"] = payload
                body = json.dumps(
                    {"message": {"role": "assistant",
                                 "content": "SUMMARY: OpenProcess opens a handle; signature HANDLE OpenProcess(DWORD, BOOL, DWORD); PROCESS_ALL_ACCESS=0x001F0FFF."},
                     "done": True}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *a):  # silence
            pass

    return H


srv = ThreadingHTTPServer(("127.0.0.1", 0), _stub_handler(BaseHTTPRequestHandler))
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
store.set_setting("ollama_url", f"http://127.0.0.1:{PORT}")
print("local stub on port", PORT)

# --- scripted chat -------------------------------------------------------------
# round 1: request_resources (chat #1 ends — the model waits)
# round 2: read_document(doc=1) — chat #2, docs now exist
# round 3: final answer

calls = {"n": 0}
# FIFO of model behaviors across the two chats:
#   chat#1: (1) request_resources + stop, (2) plain text round ends the chat
#   chat#2: (3) read_document with docs present, (4) final answer
SCRIPT = ["request", "text", "read", "final"]


async def fake_supports_tools(model):
    return True


async def fake_stream_chat(model, messages, system_prompt="", temperature=0.7, num_ctx=0, tools=None, think=None):
    calls["n"] += 1
    step = SCRIPT[(calls["n"] - 1) % len(SCRIPT)]
    names = [t["function"]["name"] for t in (tools or [])]
    STUB["last_sysp"] = system_prompt
    print(f"--- stub chat call {calls['n']} ({step}): tools offered = {names}")
    if step != "text":
        assert "request_resources" in names, "request_resources must be in the offered tools"
    if step == "request":
        yield {"tool_calls": [{
            "function": {
                "name": "request_resources",
                "arguments": {"items": [
                    {"topic": "OpenProcess Win32 API page",
                     "why": "exact signature + dwDesiredAccess flags",
                     "search_hint": "OpenProcess processthreadsapi.h"},
                ]},
            }
        }]}
        yield {"done": True, "eval_count": 5}
    elif step == "read":
        yield {"tool_calls": [{"function": {"name": "read_document", "arguments": {"doc": 1, "offset": 0, "limit": 500}}}]}
        yield {"done": True, "eval_count": 6}
    elif step == "text":
        yield {"delta": "Waiting for the requested resources."}
        yield {"done": True, "eval_count": 4}
    else:  # final
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        print(f"--- final saw read_document result: {tool_msgs[-1]['content'][:100]!r}")
        assert "OpenProcess" in tool_msgs[-1]["content"], "read_document must return the carted page text"
        yield {"delta": "Confirmed the signature from the provided doc. Writing code."}
        yield {"done": True, "eval_count": 9}


ollama.stream_chat = fake_stream_chat
ollama.model_supports_tools = fake_supports_tools
main.ollama.stream_chat = fake_stream_chat

client = TestClient(main.app)

r = client.post("/api/conversations", json={"model": "repro-model", "title": "repro"})
print("create conv:", r.status_code)
CID = r.json()["id"]

fail = 0


def check(label, cond, extra=""):
    global fail
    print(("PASS  " if cond else "FAIL  ") + label + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        fail += 1


def chat(content, attachment_ids=None):
    with client.stream(
        "POST",
        "/api/chat",
        json={"conversation_id": CID, "content": content, "model": "repro-model",
              "tools": True, "code_mode": True, "think": "off",
              "attachment_ids": attachment_ids or []},
    ) as resp:
        return [json.loads(line) for line in resp.iter_lines() if line.strip()]


# 1) chat#1: the model's request_resources call flows through the real generator
events = chat("Write a ctypes binding for OpenProcess.")
tool_events = [e for e in events if "tool" in e]
check("tool event emitted for request_resources",
      len(tool_events) == 1 and tool_events[0]["tool"]["name"] == "request_resources",
      str(tool_events)[:200])
check("tool exit 0", tool_events and tool_events[0]["tool"]["exit"] == 0)
check("tool result teaches stop-and-wait", "STOP generating" in tool_events[0]["tool"]["output"])

# 2) poll endpoint sees the pending request
req = client.get(f"/api/context/resource-request?conversation_id={CID}").json()
check("poll returns the open request", req.get("id") and len(req["items"]) == 1, str(req))
check("request item carries topic/why/search_hint",
      req["items"][0].get("topic") and req["items"][0].get("why") and req["items"][0].get("search_hint"))

# 3) cart send: raw + summarize + bad URL + bad scheme + screenshot, one request
r = client.post(
    "/api/context/cart/send",
    json={
        "conversation_id": CID,
        "items": [
            {"url": f"http://127.0.0.1:{PORT}/page", "mode": "raw", "kind": "page"},
            {"url": f"http://127.0.0.1:{PORT}/page", "mode": "summarize", "kind": "page"},
            {"url": "http://127.0.0.1:1/nope", "kind": "page"},
            {"url": "ftp://bad-scheme", "kind": "page"},
            {"kind": "image", "title": "shot.png",
             "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="},
        ],
    },
)
cart = r.json()
check("cart send 200", r.status_code == 200, r.text[:200])
check("3 attachments stored, 2 per-item errors",
      len(cart["attachments"]) == 3 and len(cart["errors"]) == 2,
      f"att={len(cart['attachments'])} err={len(cart['errors'])} {json.dumps(cart)[:300]}")
docs = [a for a in cart["attachments"] if a["kind"] == "document"]
imgs = [a for a in cart["attachments"] if a["kind"] == "image"]
check("first batch numbered 1,2", [d["doc_n"] for d in docs] == [1, 2], str([d.get("doc_n") for d in docs]))
check("screenshot rides the image path", len(imgs) == 1)
check("fulfilled reports True", cart["fulfilled"] is True)

d1 = store.get_attachment(docs[0]["id"])
d2 = store.get_attachment(docs[1]["id"])
check("raw doc keeps verbatim text", "0x001F0FFF" in (d1["text"] or ""))
check("summarize doc holds summary + meta", "SUMMARY:" in (d2["text"] or "") and d2["meta"].get("summarized") is True, str(d2["meta"]))
check("meta.source=context_resource on both",
      d1["meta"].get("source") == "context_resource" and d2["meta"].get("source") == "context_resource")
check("bad URL error is per-item", any("127.0.0.1:1/nope" in (e["url"] or "") for e in cart["errors"]))
check("bad scheme error", any("not a http(s) URL" in e["error"] for e in cart["errors"]))
check("request fulfilled after send", store.get_pending_resource_request(CID) is None)
payload = STUB.get("last_chat_payload", {})
check("summarize one-shot used the conversation's model", payload.get("model") == "repro-model")
check("summarize one-shot is non-streaming", payload.get("stream") is False)

# 4) skip path: empty items -> fulfill, nothing attached
r = client.post("/api/context/cart/send", json={"conversation_id": CID, "items": []})
check("skip path 200 + nothing attached", r.status_code == 200 and r.json()["attachments"] == [])

# 5) chat#2: synthetic user message carries [doc 1][doc 2]; model consults doc 1
events2 = chat("Resources provided per your request — use read_document to consult them.",
               attachment_ids=[docs[0]["id"], docs[1]["id"]])
tool_events2 = [e for e in events2 if "tool" in e and e["tool"]["name"] == "read_document"]
check("model's read_document(doc=1) resolved", len(tool_events2) == 1 and "OpenProcess" in tool_events2[0]["tool"]["output"],
      str(tool_events2)[:200])
msgs = client.get(f"/api/conversations/{CID}").json()["messages"]
synth = next(m for m in msgs if m["role"] == "user" and "Resources provided" in m["content"])
check("user message labeled [doc 1] [doc 2]", "[doc 1]" in synth["content"] and "[doc 2]" in synth["content"], synth["content"][:150])
linked = {a["id"]: a for m in msgs for a in m["attachments"]}
check("attachments linked with continuing idx", linked.get(docs[0]["id"], {}).get("idx") == 1 and linked.get(docs[1]["id"], {}).get("idx") == 2,
      str(linked))

# 6) second batch: numbering must CONTINUE at [doc 3]
r = client.post("/api/context/cart/send",
                json={"conversation_id": CID, "items": [{"url": f"http://127.0.0.1:{PORT}/page", "mode": "raw", "kind": "page"}]})
third = [a for a in r.json()["attachments"] if a["kind"] == "document"][0]
check("second batch continues at [doc 3]", third["doc_n"] == 3, str(third))

# 7) normalize-don't-reject (unit)
check("single dict normalized", main.clean_resource_items({"topic": "single dict works"})[0]["topic"] == "single dict works")
check("bare string normalized", main.clean_resource_items("bare string works")[0]["topic"] == "bare string works")
ok = main.clean_resource_items([{"topic": "  "}, {"why": "no topic"}, {"topic": "real topic"}])
check("junk dropped", len(ok) == 1 and ok[0]["topic"] == "real topic")
check("clamped to 10", len(main.clean_resource_items([{"topic": f"t{i}"} for i in range(30)])) == 10)
try:
    main.clean_resource_items([{"why": "no topic"}])
    check("empty raises teaching error", False)
except ValueError as exc:
    check("empty raises teaching error", "topic" in str(exc))

# 8) off-template tool-call healing (image (4) deadlock: the model leaked its
#    special tokens + a call:NAME[k:v] shape as CONTENT; the old fallback only
#    accepted bare JSON, so the turn ended as "final answer" garbage and the
#    model waited forever for a tool response that never came)
check("heal <|tool_call|> + call:NAME[k:v]",
      main.detect_content_tool_call(
          "<|tool_call|>call:read_document[doc:1]<|tool_call|><|tool_response> Unben "
      ) == {"name": "read_document", "args": {"doc": 1}})
check("heal NAME{json}", main.detect_content_tool_call('read_document{"doc": 2}') == {"name": "read_document", "args": {"doc": 2}})
check("heal NAME(k=v, k=v)", main.detect_content_tool_call("read_document(doc=1, offset=0)") == {"name": "read_document", "args": {"doc": 1, "offset": 0}})
check("heal with surrounding prose-free think tail", main.detect_content_tool_call(
    "</think>\n<|tool_call|>call:read_document[doc:1]<|tool_response>") == {"name": "read_document", "args": {"doc": 1}})
check("unknown name NOT healed", main.detect_content_tool_call("call:read_doc[doc:1]") is None)
check("prose NOT healed", main.detect_content_tool_call("see doc:1 for details") is None)
check("plain text still None", main.detect_content_tool_call("I will now write the code.") is None)
check("bare JSON still heals (regression)", main.detect_content_tool_call('{"name": "read_document", "arguments": {"doc": 1}}') == {"name": "read_document", "args": {"doc": 1}})
check("fenced JSON still heals (regression)", main.detect_content_tool_call('```\n{"name": "ws_ls", "arguments": {}}\n```') == {"name": "ws_ls", "args": {}})

# 8) build-mode directive carries the discipline text (appended to sys_prompt,
#    NOT stamped into sysp.txt or the conversation's stored prompt)
check("REFERENCE DISCIPLINE appended to the code-mode sysprompt", "REFERENCE DISCIPLINE" in (STUB.get("last_sysp") or ""))
check("FILE-FIRST delivery rule in the code-mode sysprompt", "FILE-FIRST DELIVERY" in (STUB.get("last_sysp") or ""))
check("per-turn ws_write reminder present", "Deliver FILES via ws_write" in (STUB.get("last_sysp") or ""))

# 9) editor delete: create a file + folder via the real endpoints, delete them.
# editor_root() is hardcoded to ~/Documents/.scratch — redirect it to the temp
# dir so the test never touches the user's real scratch.
SCRATCH = Path(TMP) / "scratch"
main.editor_root = lambda: SCRATCH
ws = Path(TMP) / "workspace"
store.set_setting("workspace_root", str(ws))
r = client.post("/api/editor/file", json={"filename": "del-me/del.py", "code": "x = 1"})
check("editor file saved", r.status_code == 200 and (SCRATCH / "del-me" / "del.py").is_file(), r.text[:120])
r = client.post("/api/editor/delete", json={"path": "del-me/del.py"})
check("editor delete file", r.status_code == 200 and not (SCRATCH / "del-me" / "del.py").exists())
check("editor delete parent dir left", (SCRATCH / "del-me").is_dir())
r = client.post("/api/editor/delete", json={"path": "del-me"})
check("editor delete dir (tree)", r.status_code == 200 and not (SCRATCH / "del-me").exists())
r = client.post("/api/editor/delete", json={"path": "../outside.txt"})
check("editor delete refuses traversal", r.status_code == 422)
r = client.post("/api/editor/delete", json={"path": ""})
check("editor delete refuses root", r.status_code == 422)
r = client.post("/api/editor/delete", json={"path": "nope.txt"})
check("editor delete 404", r.status_code == 404)

# 10) /logsave export: seed messages (with thinking + tool), export all formats.
# Markers are concatenated — a literal opener in this file gets eaten by the
# tool pipeline (observed), so never spell it out directly.
OPEN, CLOSE = "<" + "think>", "</" + "think" + ">"
mid = store.add_message(CID, "user", "Write the ctypes binding.")["id"]
store.attach_to_message([docs[0]["id"]], mid, CID)
store.add_message(CID, "assistant", f"{OPEN}I should ask for the OpenProcess docs first.{CLOSE}Confirmed the signature: HANDLE OpenProcess(DWORD, BOOL, DWORD). Writing code now.")
store.add_message(CID, "tool", "[doc 1 · OpenProcess.txt · chars 0-118 of 118]\nHANDLE OpenProcess(...)")
r = client.post(f"/api/conversations/{CID}/export", json={"format": "md"})
check("export md 200", r.status_code == 200, r.text[:150])
md_path = Path(r.json()["path"])
check("export md file exists", md_path.is_file())
md_text = md_path.read_text(encoding="utf-8")
check("md has USER/ASSISTANT/TOOL headers", "## USER #1" in md_text and "## ASSISTANT #1" in md_text and "## TOOL #1" in md_text)
check("md thinking is a highlighted quote", "> **◈ thinking**" in md_text and "I should ask" in md_text)
check("md answer excludes the think text", "Confirmed the signature" in md_text and md_text.count("I should ask") == 1)
check("md doc label carried", "[doc 1 · OpenProcess.txt" in md_text or "OpenProcess.txt" in md_text)
r = client.post(f"/api/conversations/{CID}/export", json={"format": "json"})
j = json.loads(Path(r.json()["path"]).read_text(encoding="utf-8"))
asst = [m for m in j["messages"] if m["role"] == "assistant" and "HANDLE OpenProcess(DWORD" in m["content"]][0]
check("json thinking in its own field", asst["thinking"] == "I should ask for the OpenProcess docs first." and "I should ask" not in asst["content"])
check("json content clean", "Confirmed the signature" in asst["content"])
r = client.post(f"/api/conversations/{CID}/export", json={"format": "txt"})
t = Path(r.json()["path"]).read_text(encoding="utf-8")
check("txt keeps both sections", "~~~~ thinking ~~~~" in t and "~~~~ answer ~~~~" in t and "Confirmed the signature" in t)
r = client.post(f"/api/conversations/{CID}/export", json={"format": "yaml"})
check("export bad format 422", r.status_code == 422)
r = client.post("/api/conversations/999999/export", json={"format": "md"})
check("export unknown conversation 404", r.status_code == 404)
check("exports land in workspace su1ra-logs", md_path.parent.name == "su1ra-logs" and md_path.parent.parent == ws)

print()
print("ALL PASS" if fail == 0 else f"{fail} FAILURES")
sys.exit(1 if fail else 0)
