"""
agents/rag_agent.py — Retrieval-Augmented Generation (RAG) for Hermes.

Architecture:
  • Documents are chunked into overlapping segments.
  • Each chunk is embedded via Ollama's /api/embeddings endpoint (uses the
    current model — no extra embedding model needed).
  • Embeddings + chunks are stored in JSON files under RAG_DIR/{user_id}/.
  • On each query, cosine similarity retrieves the top-k most relevant chunks,
    which are injected into the LLM context as "Relevant Knowledge".

Falls back to keyword (BM25-style) search if Ollama embeddings are unavailable.

Public API:
    rag = RAGAgent()
    doc_id = await rag.add_document(user_id, filename, text)
    context = await rag.retrieve(user_id, query)        → str to inject into prompt
    docs    = rag.list_documents(user_id)               → list[dict]
    rag.delete_document(user_id, doc_id)
    rag.clear(user_id)
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────
CHUNK_SIZE    = 600      # chars per chunk
CHUNK_OVERLAP = 100      # overlap between consecutive chunks
TOP_K         = 4        # chunks to retrieve per query
MIN_SCORE     = 0.10     # minimum cosine similarity to include
MAX_CTX_CHARS = 2500     # max total chars injected into prompt


# ── Helpers ───────────────────────────────────────────────────────────────

def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks of ~CHUNK_SIZE chars."""
    # Prefer splitting on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) + 1 <= CHUNK_SIZE:
            current = (current + " " + sent).strip()
        else:
            if current:
                chunks.append(current)
            # carry overlap from end of previous chunk
            tail = current[-CHUNK_OVERLAP:] if len(current) > CHUNK_OVERLAP else current
            current = (tail + " " + sent).strip()
    if current:
        chunks.append(current)
    return chunks or [text[:CHUNK_SIZE]]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


def _bm25_score(query: str, text: str) -> float:
    """Simple keyword overlap score as fallback."""
    q_words = set(re.findall(r'\w+', query.lower()))
    t_words = re.findall(r'\w+', text.lower())
    if not q_words or not t_words:
        return 0.0
    matches = sum(1 for w in t_words if w in q_words)
    return matches / (len(t_words) ** 0.5 + 1)


async def _embed(text: str) -> list[float] | None:
    """Call Ollama /api/embeddings. Returns None on failure."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{config.OLLAMA_URL}/api/embeddings",
                json={"model": config.OLLAMA_MODEL, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json().get("embedding")
    except Exception as e:
        logger.debug(f"Ollama embedding failed: {e}")
        return None


# ── Storage helpers ───────────────────────────────────────────────────────

def _user_dir(user_id: str) -> Path:
    p = config.RAG_DIR / str(user_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _index_path(user_id: str) -> Path:
    return _user_dir(user_id) / "index.json"


def _chunks_path(user_id: str) -> Path:
    return _user_dir(user_id) / "chunks.json"


def _load_index(user_id: str) -> dict:
    p = _index_path(user_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"documents": {}}


def _save_index(user_id: str, index: dict) -> None:
    _index_path(user_id).write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_chunks(user_id: str) -> list[dict]:
    p = _chunks_path(user_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_chunks(user_id: str, chunks: list[dict]) -> None:
    _chunks_path(user_id).write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── RAGAgent ──────────────────────────────────────────────────────────────

# Special user_id for shared global knowledge (injected via inject_knowledge.py)
GLOBAL_USER_ID = "__global__"


class RAGAgent:
    """Per-user RAG knowledge base with shared global knowledge layer."""

    async def add_document(
        self, user_id: int | str, filename: str, text: str
    ) -> str:
        """
        Chunk, embed, and index a document.
        Returns the doc_id string.
        """
        uid = str(user_id)
        doc_id = hashlib.md5(f"{filename}{text[:200]}".encode()).hexdigest()[:12]

        raw_chunks = _chunk_text(text)
        logger.info(
            f"RAG add_document: user={uid}, file={filename!r}, "
            f"{len(raw_chunks)} chunks"
        )

        new_chunks: list[dict] = []
        for i, chunk_text in enumerate(raw_chunks):
            embedding = await _embed(chunk_text)
            new_chunks.append({
                "id":        f"{doc_id}_{i}",
                "doc_id":    doc_id,
                "text":      chunk_text,
                "embedding": embedding,   # None if Ollama unavailable
            })

        # Merge into existing chunks (remove old version of same doc_id first)
        existing = [c for c in _load_chunks(uid) if c["doc_id"] != doc_id]
        _save_chunks(uid, existing + new_chunks)

        # Update index
        index = _load_index(uid)
        index["documents"][doc_id] = {
            "filename":    filename,
            "chunks":      len(raw_chunks),
            "added_at":    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "has_embeddings": any(c["embedding"] for c in new_chunks),
        }
        _save_index(uid, index)

        logger.info(f"RAG indexed doc_id={doc_id} for user={uid}")
        return doc_id

    async def retrieve(self, user_id: int | str, query: str) -> str:
        """
        Retrieve top-k chunks relevant to query.
        Combines user-specific knowledge + global knowledge base.
        Returns a formatted string ready to inject into the system prompt,
        or "" if knowledge base is empty.
        """
        uid = str(user_id)
        chunks = _load_chunks(uid)

        # Merge in global knowledge (available to all users)
        if uid != GLOBAL_USER_ID:
            global_chunks = _load_chunks(GLOBAL_USER_ID)
            chunks = chunks + global_chunks

        if not chunks:
            return ""

        # Try semantic (embedding-based) retrieval first
        q_embed = await _embed(query)

        scored: list[tuple[float, dict]] = []
        for chunk in chunks:
            if q_embed and chunk.get("embedding"):
                score = _cosine(q_embed, chunk["embedding"])
            else:
                score = _bm25_score(query, chunk["text"])
            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [(s, c) for s, c in scored[:TOP_K] if s >= MIN_SCORE]

        if not top:
            return ""

        # Format for injection — load both user and global indices
        index       = _load_index(uid)
        global_idx  = _load_index(GLOBAL_USER_ID)
        parts: list[str] = []
        total_chars = 0
        for score, chunk in top:
            doc_id   = chunk["doc_id"]
            doc_info = index["documents"].get(doc_id) or global_idx["documents"].get(doc_id, {})
            source   = doc_info.get("filename", "unknown")
            snippet  = chunk["text"]
            if total_chars + len(snippet) > MAX_CTX_CHARS:
                snippet = snippet[: MAX_CTX_CHARS - total_chars]
            parts.append(f"[{source}]\n{snippet}")
            total_chars += len(snippet)
            if total_chars >= MAX_CTX_CHARS:
                break

        return "\n\n---\n\n".join(parts)

    def list_documents(self, user_id: int | str) -> list[dict]:
        """Return list of indexed documents for this user."""
        index = _load_index(str(user_id))
        result = []
        for doc_id, info in index["documents"].items():
            result.append({"doc_id": doc_id, **info})
        return result

    def delete_document(self, user_id: int | str, doc_id: str) -> bool:
        """Delete a document and its chunks. Returns True if found."""
        uid = str(user_id)
        index = _load_index(uid)
        if doc_id not in index["documents"]:
            return False
        del index["documents"][doc_id]
        _save_index(uid, index)
        chunks = [c for c in _load_chunks(uid) if c["doc_id"] != doc_id]
        _save_chunks(uid, chunks)
        return True

    def clear(self, user_id: int | str) -> int:
        """Delete all documents for this user. Returns number of docs deleted."""
        uid = str(user_id)
        index = _load_index(uid)
        count = len(index["documents"])
        _save_index(uid, {"documents": {}})
        _save_chunks(uid, [])
        return count
