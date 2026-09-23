import asyncio
import json
import os
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import ollama
import store

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST = PROJECT_ROOT / "frontend" / "dist"

store.init_db()

app = FastAPI(title="Su1ra")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    conversation_id: int
    content: str
    model: str = ""


class ConversationCreate(BaseModel):
    title: str = ""
    model: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    context_length: int = 0


class ConversationUpdate(BaseModel):
    title: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    temperature: float | None = None
    context_length: int | None = None


class SettingsUpdate(BaseModel):
    ollama_url: str


@app.get("/api/status")
async def status():
    return await ollama.server_status()


@app.get("/api/models")
async def models():
    return {"models": await ollama.list_models()}


@app.get("/api/settings")
async def get_settings():
    return {"ollama_url": store.get_setting("ollama_url") or ollama.DEFAULT_URL}


@app.patch("/api/settings")
async def update_settings(body: SettingsUpdate):
    if not body.ollama_url.startswith(("http://", "https://")):
        raise HTTPException(422, "ollama_url must start with http:// or https://")
    store.set_setting("ollama_url", body.ollama_url.rstrip("/"))
    return {"ok": True, "ollama_url": body.ollama_url.rstrip("/")}


@app.post("/api/eject")
async def eject():
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/IM", "ollama.exe"], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "ollama serve"], capture_output=True)
    for _ in range(10):
        if not (await ollama.server_status())["ok"]:
            break
        await asyncio.sleep(0.2)
    else:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/IM", "ollama.exe"], capture_output=True)
        else:
            subprocess.run(["pkill", "-9", "-f", "ollama serve"], capture_output=True)
        await asyncio.sleep(0.3)
    return {"ok": True, "server_ok": (await ollama.server_status())["ok"]}


@app.post("/api/connect")
async def connect():
    return await ollama.ensure_running()


@app.get("/api/conversations")
async def conversations():
    return {"conversations": store.list_conversations()}


@app.post("/api/conversations")
async def create_conversation(body: ConversationCreate):
    return store.create_conversation(
        body.title, body.model, body.system_prompt, body.temperature, body.context_length
    )


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: int):
    conversation = store.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return {"conversation": conversation, "messages": store.get_messages(conversation_id)}


@app.patch("/api/conversations/{conversation_id}")
async def update_conversation(conversation_id: int, body: ConversationUpdate):
    updated = store.update_conversation(
        conversation_id,
        title=body.title,
        model=body.model,
        system_prompt=body.system_prompt,
        temperature=body.temperature,
        context_length=body.context_length,
    )
    if not updated:
        raise HTTPException(404, "Conversation not found")
    return updated


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int):
    if not store.delete_conversation(conversation_id):
        raise HTTPException(404, "Conversation not found")
    return {"ok": True}


@app.post("/api/chat")
async def chat(body: ChatRequest):
    conversation = store.get_conversation(body.conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    content = body.content.strip()
    if not content:
        raise HTTPException(422, "Empty message")
    model = body.model or conversation["model"]
    if not model:
        raise HTTPException(422, "No model selected")

    store.add_message(body.conversation_id, "user", content)
    if not conversation["title"]:
        store.update_conversation(body.conversation_id, title=content[:60])
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in store.get_messages(body.conversation_id)
    ]

    async def generator():
        accumulated = ""
        saved = False

        def save_partial():
            nonlocal saved
            if accumulated.strip() and not saved:
                store.add_message(body.conversation_id, "assistant", accumulated.strip())
                saved = True

        try:
            async for chunk in ollama.stream_chat(
                model,
                history,
                conversation["system_prompt"],
                conversation["temperature"],
                conversation["context_length"],
            ):
                if "error" in chunk:
                    save_partial()
                    yield json.dumps(chunk) + "\n"
                    return
                if "delta" in chunk:
                    accumulated += chunk["delta"]
                yield json.dumps(chunk) + "\n"
            save_partial()
        finally:
            save_partial()

    return StreamingResponse(generator(), media_type="application/x-ndjson")


@app.get("/{full_path:path}")
async def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "Not found")
    if DIST.is_dir():
        candidate = (DIST / full_path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(DIST.resolve())):
            return FileResponse(candidate)
        index = DIST / "index.html"
        if index.is_file():
            return FileResponse(index)
    raise HTTPException(404, "Not found")
