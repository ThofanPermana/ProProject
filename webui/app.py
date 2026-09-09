"""
webui/app.py — Hermes Web UI with persistent named sessions.

Sessions are stored server-side via MemoryStore (same as the Telegram bot).
Each browser gets a unique ID (stored in localStorage) so sessions are per-browser.

Open http://localhost:7860
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import base64

import httpx
import uvicorn
from fastapi import FastAPI, Query, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

import config
from memory.store import MemoryStore
from agents.image_agent import analyze_image, generate_image, edit_image, image_to_video

logger = logging.getLogger(__name__)
app = FastAPI(title="Hermes WebUI")

OLLAMA_BASE = config.OLLAMA_URL
MODEL = config.OLLAMA_MODEL
_store = MemoryStore()


# ── Models ─────────────────────────────────────────────────────────────────

@app.get("/api/models")
async def get_models():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            return {"models": models, "default": MODEL}
    except Exception as e:
        return {"models": [MODEL], "default": MODEL, "error": str(e)}


# ── Session API ─────────────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions(uid: str = Query(...)):
    sessions, active = _store.list_sessions(uid)
    return {"sessions": sessions, "active": active}


class SessionCreate(BaseModel):
    name: str = ""


@app.post("/api/sessions")
async def create_session(body: SessionCreate, uid: str = Query(...)):
    name = _store.new_session(uid, body.name or None)
    sessions, active = _store.list_sessions(uid)
    return {"name": name, "sessions": sessions, "active": active}


class SessionSwitch(BaseModel):
    ref: str   # name or 1-based number


@app.post("/api/sessions/switch")
async def switch_session(body: SessionSwitch, uid: str = Query(...)):
    name = _store.switch_session(uid, body.ref)
    if name is None:
        return {"error": "Session not found"}
    history = _store.get(uid)
    sessions, active = _store.list_sessions(uid)
    return {"name": name, "history": history, "sessions": sessions, "active": active}


class SessionRename(BaseModel):
    name: str


@app.post("/api/sessions/rename")
async def rename_session(body: SessionRename, uid: str = Query(...)):
    name = _store.rename_session(uid, body.name)
    sessions, active = _store.list_sessions(uid)
    return {"name": name, "sessions": sessions, "active": active}


@app.delete("/api/sessions/{ref}")
async def delete_session(ref: str, uid: str = Query(...)):
    deleted = _store.delete_session(uid, ref)
    if deleted is None:
        return {"error": "Cannot delete — session not found or only one session"}
    history = _store.get(uid)
    sessions, active = _store.list_sessions(uid)
    return {"deleted": deleted, "history": history, "sessions": sessions, "active": active}


# ── History ─────────────────────────────────────────────────────────────────

@app.get("/api/history")
async def get_history(uid: str = Query(...)):
    return {"history": _store.get(uid)}


# ── Image API ───────────────────────────────────────────────────────────────

@app.post("/api/image/analyze")
async def api_analyze(uid: str = Query(...),
                       file: UploadFile = File(...),
                       question: str = Form(default="")):
    img_bytes = await file.read()
    try:
        result = await analyze_image(img_bytes, question or "Describe this image in detail.")
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    _store.append(uid, "user", f"[Image uploaded] {question}" if question else "[Image uploaded — describe it]")
    _store.append(uid, "assistant", result)
    return {"text": result}


@app.post("/api/image/generate")
async def api_generate(uid: str = Query(...), prompt: str = Form(...), negative_prompt: str = Form(default="")):
    try:
        img_bytes = await generate_image(prompt, negative_prompt=negative_prompt)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    b64 = base64.standard_b64encode(img_bytes).decode()
    _store.append(uid, "user", f"[Generated image prompt: {prompt}]")
    _store.append(uid, "assistant", f"[Image generated for: {prompt}]")
    return {"image_b64": b64, "prompt": prompt}


@app.post("/api/image/edit")
async def api_edit(uid: str = Query(...),
                   file: UploadFile = File(...),
                   instruction: str = Form(...)):
    img_bytes = await file.read()
    try:
        new_img, desc = await edit_image(img_bytes, instruction)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    b64 = base64.standard_b64encode(new_img).decode()
    _store.append(uid, "user", f"[Edit image: {instruction}]")
    _store.append(uid, "assistant", f"[Edited image. Original: {desc}]")
    return {"image_b64": b64, "description": desc, "instruction": instruction}


@app.post("/api/image/video")
async def api_video(uid: str = Query(...),
                    file: UploadFile = File(...),
                    prompt: str = Form(default=""),
                    negative_prompt: str = Form(default=""),
                    duration: int = Form(default=5)):
    img_bytes = await file.read()
    try:
        video_bytes = await image_to_video(img_bytes, prompt=prompt, negative_prompt=negative_prompt, duration=duration)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    # Save to outputs/ so it's always retrievable from disk
    import time, pathlib
    out_dir = pathlib.Path("outputs/videos")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{uid}_{int(time.time())}.mp4"
    out_path.write_bytes(video_bytes)
    _store.append(uid, "user", f"[Image-to-video: {prompt or '(no prompt)'}]")
    _store.append(uid, "assistant", f"[Video generated → {out_path}]")
    # Return raw MP4 bytes so the browser can create a proper Blob URL
    from fastapi.responses import Response
    return Response(content=video_bytes, media_type="video/mp4")


# ── Chat (streaming, persisted) ─────────────────────────────────────────────

class ChatRequest(BaseModel):
    uid: str
    model: str = MODEL
    message: str
    system: str = ""


@app.post("/api/chat")
async def chat_stream(req: ChatRequest):
    # Append user message to store
    _store.append(req.uid, "user", req.message)
    history = _store.get(req.uid)

    payload = {
        "model": req.model,
        "messages": history,
        "stream": True,
    }
    if req.system:
        payload["system"] = req.system

    async def generate():
        full_reply = []
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST", f"{OLLAMA_BASE}/api/chat", json=payload
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            chunk = data.get("message", {}).get("content", "")
                            if chunk:
                                full_reply.append(chunk)
                                yield f"data: {json.dumps({'content': chunk})}\n\n"
                            if data.get("done"):
                                yield "data: [DONE]\n\n"
                        except Exception:
                            continue
        except (httpx.ReadError, httpx.RemoteProtocolError):
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if full_reply:
                _store.append(req.uid, "assistant", "".join(full_reply))

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Frontend ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hermes WebUI</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f0f0f; color: #e0e0e0; height: 100vh; display: flex; overflow: hidden; }

  /* ── Sidebar ── */
  #sidebar {
    width: 230px; min-width: 230px; background: #141414; border-right: 1px solid #222;
    display: flex; flex-direction: column; transition: width .2s, min-width .2s;
  }
  #sidebar.collapsed { width: 0; min-width: 0; overflow: hidden; }
  #sidebar-header {
    padding: 14px 12px 10px; font-size: 0.75rem; color: #666; text-transform: uppercase;
    letter-spacing: .06em; display: flex; align-items: center; justify-content: space-between;
  }
  #new-session-btn {
    background: #1e3a5f; color: #8fc0f8; border: none; border-radius: 6px;
    padding: 5px 10px; font-size: 0.78rem; cursor: pointer; white-space: nowrap;
  }
  #new-session-btn:hover { background: #2a5490; }
  #session-list { flex: 1; overflow-y: auto; padding: 4px 8px; }
  .session-item {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 10px; border-radius: 8px; cursor: pointer; font-size: 0.87rem;
    color: #bbb; margin-bottom: 2px; gap: 6px;
  }
  .session-item:hover { background: #1e1e1e; color: #eee; }
  .session-item.active { background: #1a2a3a; color: #8fc0f8; font-weight: 600; }
  .session-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .session-meta { font-size: 0.7rem; color: #555; white-space: nowrap; }
  .session-del {
    background: none; border: none; color: #555; cursor: pointer; font-size: 0.85rem;
    padding: 0 2px; flex-shrink: 0; line-height: 1;
  }
  .session-del:hover { color: #e05; }
  #sidebar-footer { padding: 10px 12px; border-top: 1px solid #222; }
  #rename-input {
    width: 100%; background: #1e1e1e; color: #ddd; border: 1px solid #333;
    border-radius: 6px; padding: 6px 9px; font-size: 0.83rem; outline: none;
  }
  #rename-input:focus { border-color: #4a7fc1; }

  /* ── Commands panel ── */
  #cmd-panel {
    border-top: 1px solid #222; font-size: 0.72rem; color: #666;
    overflow: hidden; max-height: 0; transition: max-height .3s ease;
  }
  #cmd-panel.open { max-height: 420px; overflow-y: auto; }
  #cmd-toggle {
    width: 100%; background: none; border: none; border-top: 1px solid #222;
    color: #555; font-size: 0.72rem; padding: 7px 12px; cursor: pointer;
    text-align: left; display: flex; justify-content: space-between;
  }
  #cmd-toggle:hover { color: #aaa; background: #181818; }
  #cmd-panel ul { list-style: none; padding: 6px 12px 10px; margin: 0; display: flex; flex-direction: column; gap: 5px; }
  #cmd-panel li { line-height: 1.45; }
  #cmd-panel code { background: #1e1e1e; color: #8fc0f8; border-radius: 4px; padding: 1px 5px; font-size: 0.71rem; }
  #cmd-panel .cmd-save { color: #4a8; font-size: 0.68rem; display: block; margin-top: 1px; }
  #cmd-panel .cmd-sec { color: #888; font-size: 0.69rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; margin-top: 6px; }

  /* ── Main ── */
  #main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  header {
    padding: 12px 16px; background: #1a1a1a; border-bottom: 1px solid #2a2a2a;
    display: flex; align-items: center; gap: 10px;
  }
  #toggle-sidebar {
    background: none; border: none; color: #888; font-size: 1.1rem; cursor: pointer; padding: 2px 6px;
  }
  #toggle-sidebar:hover { color: #ddd; }
  header h1 { font-size: 1.05rem; font-weight: 600; color: #fff; }
  #session-title { font-size: 0.82rem; color: #5a9fd4; }
  #model-select {
    margin-left: auto; background: #2a2a2a; color: #ddd; border: 1px solid #444;
    border-radius: 6px; padding: 5px 10px; font-size: 0.85rem; cursor: pointer;
  }

  /* ── Chat ── */
  #chat { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
  #chat.drag-over { outline: 2px dashed #4a7fc1; outline-offset: -8px; }
  .msg { max-width: 78%; padding: 12px 16px; border-radius: 14px; line-height: 1.55;
         font-size: 0.93rem; white-space: pre-wrap; word-break: break-word; }
  .user  { align-self: flex-end; background: #1e3a5f; color: #d8eaff; border-radius: 14px 14px 4px 14px; }
  .assistant { align-self: flex-start; background: #1e1e1e; color: #e0e0e0;
               border: 1px solid #2e2e2e; border-radius: 14px 14px 14px 4px; }
  .assistant .role { font-size: 0.75rem; color: #888; margin-bottom: 4px; }
  .msg img { max-width: 100%; border-radius: 8px; margin-top: 6px; display: block; }
  .img-caption { font-size: 0.78rem; color: #888; margin-top: 4px; }

  /* ── Image action panel (shown after upload) ── */
  #img-action-panel {
    display: none; flex-direction: column; gap: 0;
    background: #111d2e; border-top: 2px solid #2a4a7f;
  }
  #img-action-panel.visible { display: flex; }
  #img-action-top {
    display: flex; align-items: center; gap: 12px; padding: 10px 16px;
  }
  #img-preview { width: 72px; height: 72px; object-fit: cover; border-radius: 8px;
                 border: 2px solid #2a4a7f; flex-shrink: 0; }
  #img-meta { flex: 1; min-width: 0; }
  #img-preview-name { font-size: 0.82rem; color: #8fc0f8; display: block;
                      overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #img-preview-hint { font-size: 0.73rem; color: #556; margin-top: 2px; }
  #img-remove-btn { background: none; border: none; color: #556; font-size: 1.1rem;
                    cursor: pointer; padding: 4px; flex-shrink: 0; }
  #img-remove-btn:hover { color: #e05; }
  #img-action-btns {
    display: flex; gap: 8px; padding: 0 16px 12px;
  }
  .img-act-btn {
    flex: 1; border: none; border-radius: 10px; padding: 9px 12px;
    font-size: 0.88rem; font-weight: 600; cursor: pointer;
    display: flex; align-items: center; justify-content: center; gap: 6px;
  }
  #act-send { background: #1e3a5f; color: #8fc0f8; }
  #act-send:hover { background: #2a5490; }
  #act-video { background: #2a1e00; color: #fda060; border: 1px solid #5a3a00; }
  #act-video:hover { background: #3a2800; }

  /* ── Footer ── */
  footer {
    padding: 12px 16px; background: #1a1a1a; border-top: 1px solid #2a2a2a;
    display: flex; gap: 8px; align-items: flex-end;
  }
  #input {
    flex: 1; background: #2a2a2a; color: #e0e0e0; border: 1px solid #3a3a3a;
    border-radius: 10px; padding: 10px 14px; font-size: 0.93rem; resize: none;
    outline: none; max-height: 120px; overflow-y: auto;
  }
  #input:focus { border-color: #4a7fc1; }
  #send-btn {
    background: #1e3a5f; color: #8fc0f8; border: none; border-radius: 10px;
    padding: 10px 18px; font-size: 0.9rem; cursor: pointer; font-weight: 600;
  }
  #send-btn:hover { background: #2a5490; }
  #send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  #clear-btn {
    background: #2a2a2a; color: #888; border: 1px solid #3a3a3a; border-radius: 10px;
    padding: 10px 14px; font-size: 0.85rem; cursor: pointer;
  }
  #clear-btn:hover { background: #333; }
  #upload-btn {
    background: #2a2a2a; color: #888; border: 1px solid #3a3a3a; border-radius: 10px;
    padding: 10px 13px; font-size: 1rem; cursor: pointer; line-height: 1;
  }
  #upload-btn:hover { background: #333; color: #adf; }
  #file-input { display: none; }

  /* ── Generate modal ── */
  #gen-modal {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,.7);
    align-items: center; justify-content: center; z-index: 100;
  }
  #gen-modal.open { display: flex; }
  #gen-box {
    background: #1a1a1a; border: 1px solid #333; border-radius: 14px;
    padding: 24px; width: 420px; display: flex; flex-direction: column; gap: 12px;
  }
  #gen-box h2 { font-size: 1rem; color: #fff; }
  #gen-prompt {
    background: #2a2a2a; color: #e0e0e0; border: 1px solid #3a3a3a;
    border-radius: 8px; padding: 10px 12px; font-size: 0.9rem; resize: vertical;
    outline: none; min-height: 80px;
  }
  #gen-prompt:focus { border-color: #4a7fc1; }
  #gen-negative {
    background: #2a2a2a; color: #e0e0e0; border: 1px solid #3a3a3a;
    border-radius: 8px; padding: 8px 12px; font-size: 0.85rem; resize: none;
    outline: none; min-height: 48px;
  }
  #gen-negative:focus { border-color: #4a7fc1; }
  #gen-negative::placeholder { color: #555; }
  .gen-label { font-size: 0.75rem; color: #888; margin-bottom: -6px; }
  .gen-row { display: flex; gap: 8px; justify-content: flex-end; }
  .gen-row button { border-radius: 8px; padding: 8px 16px; font-size: 0.88rem; cursor: pointer; border: none; }
  #gen-cancel { background: #2a2a2a; color: #aaa; }
  #gen-go { background: #1e3a5f; color: #8fc0f8; font-weight: 600; }
  #gen-go:disabled { opacity: 0.5; }

  /* ── Video prompt modal ── */
  #vid-modal {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,.75);
    align-items: center; justify-content: center; z-index: 100;
  }
  #vid-modal.open { display: flex; }
  #vid-box {
    background: #1a1a1a; border: 1px solid #5a3a00; border-radius: 14px;
    padding: 24px; width: 440px; display: flex; flex-direction: column; gap: 14px;
  }
  #vid-box h2 { font-size: 1rem; color: #fda060; }
  #vid-box .vid-preview-row { display: flex; align-items: center; gap: 12px; }
  #vid-thumb { width: 80px; height: 80px; object-fit: cover; border-radius: 8px;
               border: 1px solid #5a3a00; flex-shrink: 0; }
  #vid-box .vid-hint {
    font-size: 0.82rem; color: #888; line-height: 1.5;
  }
  #vid-prompt {
    background: #2a2a2a; color: #e0e0e0; border: 1px solid #3a3a3a;
    border-radius: 8px; padding: 10px 12px; font-size: 0.9rem; resize: vertical;
    outline: none; min-height: 72px;
  }
  #vid-prompt:focus { border-color: #fda060; }
  #vid-examples { display: flex; flex-wrap: wrap; gap: 6px; }
  .vid-ex {
    background: #2a1e00; color: #fda060; border: 1px solid #5a3a00;
    border-radius: 20px; padding: 4px 12px; font-size: 0.78rem; cursor: pointer;
  }
  .vid-ex:hover { background: #3a2800; }
  #vid-char { font-size: 0.72rem; color: #555; text-align: right; }
  #vid-negative {
    background: #2a2a2a; color: #e0e0e0; border: 1px solid #3a3a3a;
    border-radius: 8px; padding: 8px 12px; font-size: 0.85rem; resize: none;
    outline: none; min-height: 48px;
  }
  #vid-negative:focus { border-color: #fda060; }
  #vid-negative::placeholder { color: #555; }
  .vid-label { font-size: 0.75rem; color: #888; margin-bottom: -6px; }
  .vid-dur-row { display: flex; gap: 8px; align-items: center; }
  .vid-dur-row span { font-size: 0.75rem; color: #888; }
  .dur-btn {
    background: #2a1e00; color: #fda060; border: 1px solid #5a3a00;
    border-radius: 20px; padding: 4px 14px; font-size: 0.8rem; cursor: pointer;
  }
  .dur-btn.active { background: #5a3a00; border-color: #fda060; font-weight: 700; }
  .dur-btn:hover { background: #3a2800; }
  .vid-row { display: flex; gap: 8px; justify-content: flex-end; }
  .vid-row button { border-radius: 8px; padding: 8px 16px; font-size: 0.88rem; cursor: pointer; border: none; }
  #vid-cancel { background: #2a2a2a; color: #aaa; }
  #vid-go { background: #5a3a00; color: #fda060; font-weight: 600; border: 1px solid #7a5000; }
  #vid-go:not(:disabled):hover { background: #7a5000; }
  #vid-go:disabled { opacity: 0.4; cursor: not-allowed; }

  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
</style>
</head>
<body>

<!-- Sidebar -->
<div id="sidebar">
  <div id="sidebar-header">
    <span>Sessions</span>
    <button id="new-session-btn" title="New session">+ New</button>
  </div>
  <div id="session-list"></div>
  <div id="sidebar-footer">
    <input id="rename-input" placeholder="Rename active session…" maxlength="40" />
  </div>
  <button id="cmd-toggle">Commands <span id="cmd-arrow">▼</span></button>
  <div id="cmd-panel">
    <ul>
      <li class="cmd-sec">Chat</li>
      <li><code>/clear</code> — hapus sesi ini</li>
      <li><code>/model</code> — lihat LLM aktif</li>
      <li><code>/ppt &lt;topik&gt;</code> — buat presentasi</li>
      <li class="cmd-sec">Security Scan</li>
      <li><code>/scan &lt;url&gt;</code> — full scan (port, SSL, header, path)
        <span class="cmd-save">→ output/scans/scan/ (.json+.txt)</span></li>
      <li><code>/dirscan &lt;url&gt;</code> — dir enumeration
        <span class="cmd-save">→ output/scans/dirscan/</span></li>
      <li><code>/dirscan &lt;url&gt; --api</code> — API-focused</li>
      <li><code>/dirscan &lt;url&gt; --deep</code> — ~300 paths</li>
      <li><code>/apiscan &lt;url&gt;</code> — detect GraphQL/REST/SOAP/gRPC
        <span class="cmd-save">→ output/scans/apiscan/</span></li>
      <li><code>/aiscan &lt;url&gt;</code> — AI-guided iterative scan
        <span class="cmd-save">→ output/scans/aiscan/</span></li>
      <li><code>/dns &lt;domain&gt;</code> — DNS lookup</li>
      <li class="cmd-sec">Web &amp; Data</li>
      <li><code>/search &lt;query&gt;</code> — web search</li>
      <li><code>/browse &lt;url&gt;</code> — summarise page</li>
      <li><code>/scrape &lt;url&gt;</code> — extract tables/text</li>
      <li><code>/scrape &lt;url&gt; --save</code> → outputs/scraped/</li>
      <li><code>/crawl &lt;url&gt;</code> — crawl internal links</li>
      <li><code>/crawl &lt;url&gt; --save</code> → outputs/scraped/</li>
    </ul>
  </div>
</div>

<!-- Main -->
<div id="main">
  <header>
    <button id="toggle-sidebar" title="Toggle sidebar">☰</button>
    <h1>⚡ Hermes</h1>
    <span id="session-title"></span>
    <select id="model-select"></select>
  </header>

  <div id="chat"></div>

  <!-- Image action panel: appears after photo upload -->
  <div id="img-action-panel">
    <div id="img-action-top">
      <img id="img-preview" src="" alt="preview" />
      <div id="img-meta">
        <span id="img-preview-name"></span>
        <span id="img-preview-hint">Type an instruction below to edit, or choose an action:</span>
      </div>
      <button id="img-remove-btn" title="Remove image">✕</button>
    </div>
    <div id="img-action-btns">
      <button class="img-act-btn" id="act-send">📤 Analyze / Edit</button>
      <button class="img-act-btn" id="act-video">🎬 Animate to Video</button>
    </div>
  </div>

  <footer>
    <input type="file" id="file-input" accept="image/*" />
    <button id="upload-btn" title="Attach image">🖼️</button>
    <textarea id="input" rows="1" placeholder="Message Hermes… or drag &amp; drop an image"></textarea>
    <button id="clear-btn" title="Clear chat">🗑️</button>
    <button id="send-btn">Send</button>
  </footer>
</div>

<!-- Generate image modal -->
<div id="gen-modal">
  <div id="gen-box">
    <h2>🎨 Generate Image</h2>
    <textarea id="gen-prompt" placeholder="Describe the image you want to generate…"></textarea>
    <p class="gen-label">Negative prompt <em>(optional)</em> — things to avoid:</p>
    <textarea id="gen-negative" rows="2" placeholder="e.g. blurry, watermark, ugly, low quality, text"></textarea>
    <div class="gen-row">
      <button id="gen-cancel">Cancel</button>
      <button id="gen-go">Generate</button>
    </div>
  </div>
</div>

<!-- Video prompt modal (required before fal.ai) -->
<div id="vid-modal">
  <div id="vid-box">
    <h2>🎬 Animate Image to Video</h2>
    <div class="vid-preview-row">
      <img id="vid-thumb" src="" alt="" />
      <p class="vid-hint">
        Describe the <strong>motion</strong> you want in the video.<br>
        Be specific — e.g. <em>“hair blowing in the wind, slow zoom out”</em>.<br>
        <span style="color:#e88;">This field is required.</span>
      </p>
    </div>
    <textarea id="vid-prompt" placeholder="e.g. camera slowly pans right, waves crashing on shore…" maxlength="300"></textarea>
    <div id="vid-examples">
      <span class="vid-ex">hair blowing in wind</span>
      <span class="vid-ex">slow zoom in</span>
      <span class="vid-ex">camera pans right</span>
      <span class="vid-ex">waves moving, clouds drifting</span>
      <span class="vid-ex">leaves rustling</span>
      <span class="vid-ex">cinematic dolly shot</span>
    </div>
    <div id="vid-char">0 / 300</div>
    <p class="vid-label">Negative prompt <em>(optional)</em> — things to avoid:</p>
    <textarea id="vid-negative" rows="2" placeholder="e.g. blurry, watermark, ugly, distorted, text"></textarea>
    <div class="vid-dur-row">
      <span>Duration:</span>
      <button class="dur-btn active" data-dur="5">5 s</button>
      <button class="dur-btn" data-dur="10">10 s</button>
      <button class="dur-btn" data-dur="15">15 s</button>
    </div>
    <div class="vid-row">
      <button id="vid-cancel">Cancel</button>
      <button id="vid-go" disabled>🎬 Generate Video</button>
    </div>
  </div>
</div>

<script>
// ── State ────────────────────────────────────────────────────────────────────
const chatEl       = document.getElementById('chat');
const inputEl      = document.getElementById('input');
const sendBtn      = document.getElementById('send-btn');
const modelSel     = document.getElementById('model-select');
const clearBtn     = document.getElementById('clear-btn');
const sidebar      = document.getElementById('sidebar');
const sessionList  = document.getElementById('session-list');
const sessionTitle = document.getElementById('session-title');
const renameInput  = document.getElementById('rename-input');
const newBtn       = document.getElementById('new-session-btn');
const toggleBtn    = document.getElementById('toggle-sidebar');
const fileInput    = document.getElementById('file-input');
const uploadBtn    = document.getElementById('upload-btn');
const imgActionPanel = document.getElementById('img-action-panel');
const imgPreview   = document.getElementById('img-preview');
const imgPreviewName = document.getElementById('img-preview-name');
const imgRemoveBtn = document.getElementById('img-remove-btn');
const actSend      = document.getElementById('act-send');
const actVideo     = document.getElementById('act-video');
const genModal     = document.getElementById('gen-modal');
const genPromptEl  = document.getElementById('gen-prompt');
const genNegEl     = document.getElementById('gen-negative');
const genGo        = document.getElementById('gen-go');
const genCancel    = document.getElementById('gen-cancel');
const vidModal     = document.getElementById('vid-modal');
const vidThumb     = document.getElementById('vid-thumb');
const vidPromptEl  = document.getElementById('vid-prompt');
const vidNegEl     = document.getElementById('vid-negative');
const vidGo        = document.getElementById('vid-go');
const vidCancel    = document.getElementById('vid-cancel');
const vidChar      = document.getElementById('vid-char');
const vidDurBtns   = document.querySelectorAll('.dur-btn');
let   vidDuration  = 5;

let streaming = false;
let activeSid = null;
let attachedFile = null;   // File object

function getUID() {
  let uid = localStorage.getItem('hermes_uid');
  if (!uid) {
    uid = 'w_' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    localStorage.setItem('hermes_uid', uid);
  }
  return uid;
}
const UID = getUID();

// ── Model selector ────────────────────────────────────────────────────────────
async function loadModels() {
  const res = await fetch('/api/models');
  const data = await res.json();
  data.models.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m; opt.textContent = m;
    if (m === data.default) opt.selected = true;
    modelSel.appendChild(opt);
  });
}

// ── Chat rendering ────────────────────────────────────────────────────────────
function renderHistory(history) {
  chatEl.innerHTML = '';
  history.forEach(msg => {
    if (msg.content.startsWith('[')) {
      // Skip internal markers silently
    } else {
      addMessage(msg.role, msg.content);
    }
  });
}

function addMessage(role, content, imgSrc) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  if (role === 'assistant') {
    div.innerHTML = `<div class="role">Hermes</div><span></span>`;
    div.querySelector('span').textContent = content;
  } else {
    if (imgSrc) {
      const img = document.createElement('img');
      img.src = imgSrc;
      div.appendChild(img);
      if (content) {
        const cap = document.createElement('div');
        cap.className = 'img-caption';
        cap.textContent = content;
        div.appendChild(cap);
      }
    } else {
      div.textContent = content;
    }
  }
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

function addImageResult(role, imgB64, caption) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  if (role === 'assistant') div.innerHTML = `<div class="role">Hermes</div>`;
  const img = document.createElement('img');
  img.src = 'data:image/jpeg;base64,' + imgB64;
  div.appendChild(img);
  if (caption) {
    const cap = document.createElement('div');
    cap.className = 'img-caption';
    cap.textContent = caption;
    div.appendChild(cap);
  }
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function appendToLast(text) {
  const spans = chatEl.querySelectorAll('.assistant span');
  const last = spans[spans.length - 1];
  if (last) { last.textContent += text; chatEl.scrollTop = chatEl.scrollHeight; }
}

function addThinking(text) {
  const div = document.createElement('div');
  div.className = 'msg assistant';
  div.innerHTML = `<div class="role">Hermes</div><span style="color:#888;font-style:italic">${text}</span>`;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

// ── Image attach ──────────────────────────────────────────────────────────────
uploadBtn.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) attachFile(fileInput.files[0]);
});

function attachFile(file) {
  if (!file.type.startsWith('image/')) { alert('Please select an image file.'); return; }
  attachedFile = file;
  imgPreview.src = URL.createObjectURL(file);
  imgPreviewName.textContent = file.name;
  imgActionPanel.classList.add('visible');
  inputEl.placeholder = 'Optional: type an edit instruction, then click Analyze/Edit…';
}

function clearAttachment() {
  attachedFile = null;
  fileInput.value = '';
  imgActionPanel.classList.remove('visible');
  inputEl.placeholder = 'Message Hermes… or drag & drop an image';
}

imgRemoveBtn.addEventListener('click', clearAttachment);

// Drag & drop on chat area
chatEl.addEventListener('dragover', e => { e.preventDefault(); chatEl.classList.add('drag-over'); });
chatEl.addEventListener('dragleave', () => chatEl.classList.remove('drag-over'));
chatEl.addEventListener('drop', e => {
  e.preventDefault();
  chatEl.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) attachFile(file);
});

// Paste image from clipboard
document.addEventListener('paste', e => {
  const items = e.clipboardData?.items || [];
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      attachFile(item.getAsFile());
      break;
    }
  }
});

// ── Analyze / Edit button ─────────────────────────────────────────────────────
actSend.addEventListener('click', () => { if (attachedFile) send(); });

// ── Image-to-Video: open required prompt modal ────────────────────────────────
actVideo.addEventListener('click', () => {
  if (!attachedFile || streaming) return;
  vidThumb.src = imgPreview.src;
  vidPromptEl.value = '';
  vidNegEl.value = '';
  vidChar.textContent = '0 / 300';
  vidDuration = 5;
  vidDurBtns.forEach(b => b.classList.toggle('active', b.dataset.dur === '5'));
  vidGo.disabled = true;
  vidModal.classList.add('open');
  vidPromptEl.focus();
});

// Duration toggle
vidDurBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    vidDuration = parseInt(btn.dataset.dur, 10);
    vidDurBtns.forEach(b => b.classList.toggle('active', b === btn));
  });
});

// Video modal — character counter + enable/disable submit
vidPromptEl.addEventListener('input', () => {
  const len = vidPromptEl.value.trim().length;
  vidChar.textContent = `${vidPromptEl.value.length} / 300`;
  vidGo.disabled = len < 3;
});

// Example chip click → insert into textarea
document.getElementById('vid-examples').addEventListener('click', e => {
  if (e.target.classList.contains('vid-ex')) {
    vidPromptEl.value = e.target.textContent;
    vidPromptEl.dispatchEvent(new Event('input'));
    vidPromptEl.focus();
  }
});

vidCancel.addEventListener('click', () => vidModal.classList.remove('open'));
vidModal.addEventListener('click', e => { if (e.target === vidModal) vidModal.classList.remove('open'); });
vidPromptEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey && !vidGo.disabled) { e.preventDefault(); vidGo.click(); }
  if (e.key === 'Escape') vidModal.classList.remove('open');
});

// ── Image-to-Video: submit ────────────────────────────────────────────────────
vidGo.addEventListener('click', async () => {
  const prompt = vidPromptEl.value.trim();
  if (!prompt || !attachedFile || streaming) return;
  vidModal.classList.remove('open');

  const file = attachedFile;
  clearAttachment();
  inputEl.value = ''; inputEl.style.height = 'auto';
  streaming = true; sendBtn.disabled = true;

  addMessage('user', `🎬 Animate: ${prompt}`);
  const think = addThinking('Animating image via fal.ai (30–90 s)…');
  try {
    const negPrompt = vidNegEl.value.trim();
    const fd = new FormData();
    fd.append('file', file);
    fd.append('prompt', prompt);
    if (negPrompt) fd.append('negative_prompt', negPrompt);
    fd.append('duration', String(vidDuration));
    const res = await fetch(`/api/image/video?uid=${UID}`, { method: 'POST', body: fd });
    const ct = res.headers.get('content-type') || '';
    if (!res.ok || ct.includes('json')) {
      const data = await res.json();
      think.remove();
      addMessage('assistant', `⚠️ ${data.error || 'Video generation failed'}`);
    } else {
      const buf = await res.arrayBuffer();
      const blob = new Blob([buf], { type: 'video/mp4' });
      const blobUrl = URL.createObjectURL(blob);
      think.remove();
      addVideoResult('assistant', blobUrl, prompt);
    }
  } catch(e) {
    think.remove();
    addMessage('assistant', `Error: ${e.message}`);
  } finally {
    streaming = false; sendBtn.disabled = false; inputEl.focus();
  }
});

function addVideoResult(role, videoUrl, caption) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  if (role === 'assistant') div.innerHTML = `<div class="role">Hermes</div>`;
  const video = document.createElement('video');
  video.src = videoUrl;
  video.controls = true;
  video.autoplay = true;
  video.loop = true;
  video.muted = true;  // autoplay requires muted in most browsers
  video.style.cssText = 'max-width:100%;border-radius:8px;margin-top:6px;display:block;';
  div.appendChild(video);
  if (caption) {
    const cap = document.createElement('div');
    cap.className = 'img-caption';
    cap.textContent = `🎬 ${caption}`;
    div.appendChild(cap);
  }
  // Download button
  const dl = document.createElement('a');
  dl.href = videoUrl;
  dl.download = `hermes_video_${Date.now()}.mp4`;
  dl.textContent = '⬇️ Download MP4';
  dl.style.cssText = 'display:inline-block;margin-top:6px;font-size:0.8rem;color:#8fc0f8;text-decoration:none;';
  div.appendChild(dl);
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

// ── Generate image modal ──────────────────────────────────────────────────────
// Right-click / long-press upload button → open generate modal
uploadBtn.addEventListener('contextmenu', e => {
  e.preventDefault();
  genNegEl.value = '';
  genModal.classList.add('open');
  genPromptEl.focus();
});
// Also: type /generate in input to open modal
inputEl.addEventListener('input', () => {
  if (inputEl.value.trimStart().startsWith('/generate')) {
    const prompt = inputEl.value.replace(/^\/generate\s*/i, '').trim();
    genPromptEl.value = prompt;
    genNegEl.value = '';
    inputEl.value = '';
    genModal.classList.add('open');
    genPromptEl.focus();
  }
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
});
genCancel.addEventListener('click', () => genModal.classList.remove('open'));
genModal.addEventListener('click', e => { if (e.target === genModal) genModal.classList.remove('open'); });

genGo.addEventListener('click', async () => {
  const prompt = genPromptEl.value.trim();
  if (!prompt) return;
  const neg = genNegEl.value.trim();
  genModal.classList.remove('open');
  genPromptEl.value = '';
  genNegEl.value = '';
  await runGenerate(prompt, neg);
});
genPromptEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); genGo.click(); }
  if (e.key === 'Escape') genModal.classList.remove('open');
});

async function runGenerate(prompt, negPrompt = '') {
  streaming = true; sendBtn.disabled = true;
  addMessage('user', `🎨 Generate: ${prompt}${negPrompt ? ` \u2014 neg: ${negPrompt}` : ''}`);
  const think = addThinking('Generating image…');
  try {
    const fd = new FormData();
    fd.append('prompt', prompt);
    if (negPrompt) fd.append('negative_prompt', negPrompt);
    const res = await fetch(`/api/image/generate?uid=${UID}`, { method: 'POST', body: fd });
    const data = await res.json();
    think.remove();
    if (data.error) { addMessage('assistant', `Error: ${data.error}`); return; }
    addImageResult('assistant', data.image_b64, `Generated: ${prompt}`);
  } catch(e) {
    think.remove();
    addMessage('assistant', `Error: ${e.message}`);
  } finally {
    streaming = false; sendBtn.disabled = false; inputEl.focus();
  }
}

// ── Send ──────────────────────────────────────────────────────────────────────
async function send() {
  const text = inputEl.value.trim();
  if ((!text && !attachedFile) || streaming) return;

  inputEl.value = '';
  inputEl.style.height = 'auto';
  streaming = true;
  sendBtn.disabled = true;

  // ── Image mode ──
  if (attachedFile) {
    const file = attachedFile;
    const previewUrl = imgPreview.src;
    clearAttachment();

    addMessage('user', text || '', previewUrl);

    if (text) {
      // Edit mode
      const think = addThinking('Editing image…');
      try {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('instruction', text);
        const res = await fetch(`/api/image/edit?uid=${UID}`, { method: 'POST', body: fd });
        const data = await res.json();
        think.remove();
        if (data.error) { addMessage('assistant', `Error: ${data.error}`); }
        else {
          if (data.description) addMessage('assistant', data.description);
          addImageResult('assistant', data.image_b64, `Edited: ${text}`);
        }
      } catch(e) {
        think.remove();
        addMessage('assistant', `Error: ${e.message}`);
      }
    } else {
      // Analyze mode
      const think = addThinking('Analyzing image…');
      try {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('question', '');
        const res = await fetch(`/api/image/analyze?uid=${UID}`, { method: 'POST', body: fd });
        const data = await res.json();
        think.remove();
        if (data.error) addMessage('assistant', `Error: ${data.error}`);
        else addMessage('assistant', data.text);
      } catch(e) {
        think.remove();
        addMessage('assistant', `Error: ${e.message}`);
      }
    }
    streaming = false; sendBtn.disabled = false; inputEl.focus();
    return;
  }

  // ── Text mode ──
  addMessage('user', text);
  const assistantDiv = addMessage('assistant', '');
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uid: UID, model: modelSel.value, message: text }),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6);
        if (payload === '[DONE]') break;
        try { appendToLast(JSON.parse(payload).content || ''); } catch {}
      }
    }
    const sr = await fetch(`/api/sessions?uid=${UID}`);
    const sd = await sr.json();
    renderSessions(sd.sessions, sd.active);
  } catch (e) {
    appendToLast('[Error: ' + e.message + ']');
  } finally {
    streaming = false; sendBtn.disabled = false; inputEl.focus();
  }
}

// ── Session API ───────────────────────────────────────────────────────────────
function renderSessions(sessions, activeId) {
  activeSid = activeId;
  sessionList.innerHTML = '';
  sessions.forEach((s, i) => {
    const item = document.createElement('div');
    item.className = 'session-item' + (s.id === activeId ? ' active' : '');
    item.innerHTML = `
      <span class="session-name" title="${s.name}">${s.name}</span>
      <span class="session-meta">${s.last_used || ''}</span>
      <button class="session-del" data-ref="${i + 1}" title="Delete">✕</button>`;
    item.querySelector('.session-name').addEventListener('click', () => switchSession(String(i + 1)));
    item.querySelector('.session-del').addEventListener('click', e => {
      e.stopPropagation();
      if (sessions.length <= 1) return alert('Cannot delete the only session.');
      if (confirm(`Delete "${s.name}"?`)) deleteSession(String(i + 1));
    });
    sessionList.appendChild(item);
  });
  const active = sessions.find(s => s.id === activeId);
  sessionTitle.textContent = active ? `· ${active.name}` : '';
}

async function loadSessions() {
  const res = await fetch(`/api/sessions?uid=${UID}`);
  const data = await res.json();
  renderSessions(data.sessions, data.active);
  const h = await fetch(`/api/history?uid=${UID}`);
  const hdata = await h.json();
  renderHistory(hdata.history);
}

async function newSession() {
  const name = prompt('Session name (leave blank for auto):') ?? '';
  const res = await fetch(`/api/sessions?uid=${UID}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  const data = await res.json();
  renderSessions(data.sessions, data.active);
  renderHistory([]);
}

async function switchSession(ref) {
  const res = await fetch(`/api/sessions/switch?uid=${UID}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ref }),
  });
  const data = await res.json();
  if (data.error) return alert(data.error);
  renderSessions(data.sessions, data.active);
  renderHistory(data.history);
}

async function renameSession(name) {
  if (!name.trim()) return;
  const res = await fetch(`/api/sessions/rename?uid=${UID}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: name.trim() }),
  });
  const data = await res.json();
  renderSessions(data.sessions, data.active);
  renameInput.value = '';
}

async function deleteSession(ref) {
  const res = await fetch(`/api/sessions/${encodeURIComponent(ref)}?uid=${UID}`, { method: 'DELETE' });
  const data = await res.json();
  if (data.error) return alert(data.error);
  renderSessions(data.sessions, data.active);
  renderHistory(data.history);
}

// ── Clear session ─────────────────────────────────────────────────────────────
clearBtn.addEventListener('click', async () => {
  if (!confirm("Clear this session's history?")) return;
  const sr = await fetch(`/api/sessions?uid=${UID}`);
  const sd = await sr.json();
  const active = sd.sessions.find(s => s.id === sd.active);
  const name = active ? active.name : 'Session';
  await fetch(`/api/sessions/${encodeURIComponent(String(sd.sessions.findIndex(s=>s.id===sd.active)+1))}?uid=${UID}`, { method: 'DELETE' });
  const nr = await fetch(`/api/sessions?uid=${UID}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  const nd = await nr.json();
  renderSessions(nd.sessions, nd.active);
  renderHistory([]);
});

// ── Events ────────────────────────────────────────────────────────────────────
toggleBtn.addEventListener('click', () => sidebar.classList.toggle('collapsed'));

// Commands panel toggle
const cmdToggle = document.getElementById('cmd-toggle');
const cmdPanel  = document.getElementById('cmd-panel');
const cmdArrow  = document.getElementById('cmd-arrow');
cmdToggle.addEventListener('click', () => {
  cmdPanel.classList.toggle('open');
  cmdArrow.textContent = cmdPanel.classList.contains('open') ? '▲' : '▼';
});

newBtn.addEventListener('click', newSession);
renameInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); renameSession(renameInput.value); }
});
sendBtn.addEventListener('click', send);
inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

// ── Init ──────────────────────────────────────────────────────────────────────
loadModels();
loadSessions();
</script>
</body>
</html>
"""



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="warning")

