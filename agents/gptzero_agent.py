"""
agents/gptzero_agent.py — GPTZero AI-content detection.

check_gptzero(text) → (report: str, score: float)

score = completely_generated_prob (0.0 → human, 1.0 → AI)

GPTZero API docs: https://gptzero.me/api
Endpoint: POST https://api.gptzero.me/v2/predict/text
"""
from __future__ import annotations

import logging

import httpx

import config

logger = logging.getLogger(__name__)

_API_URL = "https://api.gptzero.me/v2/predict/text"
_HEADERS = {
    "x-api-key": config.GPTZERO_API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Max chars per single GPTZero request (~50k token limit, keep well under)
_MAX_CHARS = 50_000


def _verdict(prob: float) -> str:
    if prob >= 0.85:
        return "🤖 AI-generated"
    elif prob >= 0.50:
        return "⚠️ Mixed (AI + Human)"
    elif prob >= 0.20:
        return "🟡 Likely Human"
    else:
        return "✅ Human-written"


def _bar(prob: float, width: int = 20) -> str:
    filled = round(prob * width)
    return "█" * filled + "░" * (width - filled)


async def check_gptzero(text: str) -> tuple[str, float]:
    """
    Send text to GPTZero and return (formatted_report, ai_probability_score).
    Score range: 0.0 (human) → 1.0 (AI).
    """
    if not config.GPTZERO_API_KEY:
        return "❌ GPTZERO_API_KEY tidak dikonfigurasi di .env.", 0.0

    trimmed = text[:_MAX_CHARS]
    payload = {
        "document": trimmed,
        "version": "2025-12-04-multilingual",
        "multilingual": True,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(_API_URL, json=payload, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"GPTZero HTTP error: {e.response.status_code} — {e.response.text}")
        return f"❌ GPTZero error {e.response.status_code}: {e.response.text[:200]}", 0.0
    except Exception as e:
        logger.error(f"GPTZero request failed: {e}")
        return f"❌ GPTZero gagal: {e}", 0.0

    doc = data.get("documents", [{}])[0]

    ai_prob    = doc.get("completely_generated_prob", 0.0)
    class_prob = doc.get("class_probabilities", {})
    burstiness = doc.get("average_generated_prob", 0.0)
    pred_class = doc.get("predicted_class", "unknown")
    sentences  = doc.get("sentences", [])

    lines = [
        "🔍 *GPTZero AI Detection Report*\n",
        f"*Overall verdict:* {_verdict(ai_prob)}",
        f"*AI probability:*  `{ai_prob * 100:.1f}%`  {_bar(ai_prob)}",
        "",
        "*Class breakdown:*",
        f"  🤖 AI-generated : `{class_prob.get('ai', 0) * 100:.1f}%`",
        f"  🔀 Mixed        : `{class_prob.get('mixed', 0) * 100:.1f}%`",
        f"  👤 Human        : `{class_prob.get('human', 0) * 100:.1f}%`",
    ]

    # Per-sentence highlights — show top 3 most AI-like sentences
    ai_sentences = sorted(
        [s for s in sentences if s.get("generated_prob", 0) >= 0.7],
        key=lambda s: s.get("generated_prob", 0),
        reverse=True,
    )[:3]

    if ai_sentences:
        lines.append("")
        lines.append("*Most AI-like sentences:*")
        for s in ai_sentences:
            prob = s.get("generated_prob", 0)
            snippet = (
                s.get("sentence", "")[:120]
                .replace("&", "&amp;")
                .replace("*", "\\*")
                .replace("_", "\\_")
            )
            lines.append(f"  `{prob * 100:.0f}%` — {snippet}…")

    lines += [
        "",
        f"*Predicted class:* `{pred_class}`",
        f"*Chars checked:*   `{len(trimmed):,}` / `{len(text):,}`",
    ]

    if len(text) > _MAX_CHARS:
        lines.append(f"_⚠️ Teks terlalu panjang, hanya {_MAX_CHARS:,} karakter pertama yang diperiksa._")

    return "\n".join(lines), ai_prob
