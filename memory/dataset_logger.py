"""
memory/dataset_logger.py — Real-time interaction logger for Hermes training data.

Setiap kali user berinteraksi dengan Hermes, data dicatat otomatis ke:
  tools/auto_dataset.jsonl  — format ChatML siap fine-tuning

Tipe interaksi yang dicatat:
  • chat      — pertanyaan + jawaban biasa
  • search    — query pencarian + ringkasan hasil
  • browse    — URL yang dibrowse + ringkasan konten
  • upload    — dokumen yang diindeks ke RAG

Format setiap entri:
{
  "messages": [
    {"role": "system",    "content": "<SYSTEM_PROMPT>"},
    {"role": "user",      "content": "<pertanyaan user>"},
    {"role": "assistant", "content": "<jawaban hermes>"}
  ],
  "_meta": {
    "type":       "chat" | "search" | "browse" | "upload",
    "user_id":    "<hash anonim>",
    "timestamp":  "2026-05-11 14:23",
    "tool_ctx":   true | false   (apakah ada augmentasi web/RAG)
  }
}

Privacy: user_id di-hash MD5 — tidak menyimpan ID asli Telegram.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Storage path ──────────────────────────────────────────────────────────
_DATASET_FILE = Path(__file__).parent.parent / "tools" / "auto_dataset.jsonl"
_DATASET_FILE.parent.mkdir(parents=True, exist_ok=True)

# Thread lock — Telegram bot is async but we write from multiple coroutines
_LOCK = threading.Lock()

# Minimum quality thresholds
_MIN_USER_LEN  = 10   # chars
_MIN_REPLY_LEN = 20   # chars


def _anon_uid(user_id: int | str) -> str:
    """One-way hash of user ID to keep dataset anonymous."""
    return hashlib.md5(str(user_id).encode()).hexdigest()[:10]


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def _is_quality(user_msg: str, reply: str) -> bool:
    if len(user_msg.strip()) < _MIN_USER_LEN:
        return False
    if len(reply.strip()) < _MIN_REPLY_LEN:
        return False
    # Skip obvious error messages
    if reply.strip().startswith(("Error:", "Gagal", "Failed", "⚠️")):
        return False
    return True


def _append(record: dict) -> None:
    """Thread-safe append of one JSONL record."""
    line = json.dumps(record, ensure_ascii=False)
    with _LOCK:
        with _DATASET_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


# ── Public logging functions (called from hermes_agent.py) ────────────────

def log_chat(
    user_id: int | str,
    user_text: str,
    reply: str,
    system_prompt: str,
    has_rag: bool = False,
    has_tool: bool = False,
) -> None:
    """Log a plain chat exchange."""
    if not _is_quality(user_text, reply):
        return
    record = {
        "messages": [
            {"role": "system",    "content": system_prompt},
            {"role": "user",      "content": user_text.strip()},
            {"role": "assistant", "content": reply.strip()},
        ],
        "_meta": {
            "type":      "chat",
            "user_id":   _anon_uid(user_id),
            "timestamp": _ts(),
            "has_rag":   has_rag,
            "has_tool":  has_tool,
        },
    }
    try:
        _append(record)
    except Exception as e:
        logger.warning(f"dataset_logger.log_chat failed: {e}")


def log_search(
    user_id: int | str,
    query: str,
    summary: str,
    system_prompt: str,
) -> None:
    """Log a /search interaction."""
    if not _is_quality(query, summary):
        return
    user_text = f"Cari informasi tentang: {query}"
    record = {
        "messages": [
            {"role": "system",    "content": system_prompt},
            {"role": "user",      "content": user_text},
            {"role": "assistant", "content": summary.strip()},
        ],
        "_meta": {
            "type":      "search",
            "query":     query,
            "user_id":   _anon_uid(user_id),
            "timestamp": _ts(),
        },
    }
    try:
        _append(record)
    except Exception as e:
        logger.warning(f"dataset_logger.log_search failed: {e}")


def log_browse(
    user_id: int | str,
    url: str,
    summary: str,
    system_prompt: str,
) -> None:
    """Log a /browse interaction."""
    if not _is_quality(url, summary):
        return
    user_text = f"Buka dan rangkum halaman web ini: {url}"
    record = {
        "messages": [
            {"role": "system",    "content": system_prompt},
            {"role": "user",      "content": user_text},
            {"role": "assistant", "content": summary.strip()},
        ],
        "_meta": {
            "type":      "browse",
            "url":       url,
            "user_id":   _anon_uid(user_id),
            "timestamp": _ts(),
        },
    }
    try:
        _append(record)
    except Exception as e:
        logger.warning(f"dataset_logger.log_browse failed: {e}")


def log_upload(
    user_id: int | str,
    filename: str,
    doc_text: str,
) -> None:
    """Log that a document was uploaded — store as a 'summarise this' training pair."""
    if len(doc_text.strip()) < 100:
        return
    # Store only a snippet so the record isn't huge
    snippet = doc_text.strip()[:1200]
    user_text = f"Ini adalah isi dokumen '{filename}'. Ringkas dan jelaskan isinya."
    record = {
        "messages": [
            {"role": "user",      "content": user_text},
            {"role": "assistant", "content": f"[Dokumen '{filename}' diindeks ke knowledge base. Snippet: {snippet[:300]}...]"},
        ],
        "_meta": {
            "type":      "upload",
            "filename":  filename,
            "user_id":   _anon_uid(user_id),
            "timestamp": _ts(),
        },
    }
    try:
        _append(record)
    except Exception as e:
        logger.warning(f"dataset_logger.log_upload failed: {e}")


# ── Stats helper ──────────────────────────────────────────────────────────

def get_stats() -> dict:
    """Return basic statistics about the auto-collected dataset."""
    if not _DATASET_FILE.exists():
        return {"total": 0, "by_type": {}, "file": str(_DATASET_FILE)}

    counts: dict[str, int] = {}
    total = 0
    try:
        for line in _DATASET_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                t = obj.get("_meta", {}).get("type", "unknown")
                counts[t] = counts.get(t, 0) + 1
                total += 1
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"dataset_logger.get_stats failed: {e}")

    return {
        "total":   total,
        "by_type": counts,
        "file":    str(_DATASET_FILE),
    }
