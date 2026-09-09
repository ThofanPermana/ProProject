"""
agents/analysis_agent.py — AI-powered text analysis for Hermes.

analyse_text(text, filename) → (formatted_report: str, json_path: Path)

The LLM produces a structured JSON with:
  - doc_type      : jenis dokumen (laporan, artikel, kode, dll)
  - language      : bahasa utama
  - summary       : ringkasan 3-5 kalimat
  - topics        : list topik utama (max 8)
  - key_points    : list poin penting (max 10)
  - entities      : {people, organizations, locations, technologies} (list masing-masing)
  - sentiment     : positif / negatif / netral
  - complexity    : rendah / sedang / tinggi
  - word_count    : jumlah kata (dihitung lokal)
  - recommendations: list saran tindak lanjut (max 5)

Saved to output/analysis/<timestamp>_<slug>.json
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from llm.client import LLMClient

logger = logging.getLogger(__name__)

_OUT_DIR = Path(__file__).parent.parent / "output" / "analysis"
_OUT_DIR.mkdir(parents=True, exist_ok=True)

_ANALYSIS_SYSTEM = """Kamu adalah analis dokumen profesional.
Tugasmu: analisis teks yang diberikan dan kembalikan hasil dalam format JSON murni (tanpa markdown fence, tanpa komentar).

Output HARUS berupa JSON valid dengan struktur persis ini:
{
  "doc_type": "string",
  "language": "string",
  "summary": "string (3-5 kalimat)",
  "topics": ["topic1", "topic2"],
  "key_points": ["poin1", "poin2"],
  "entities": {
    "people": [],
    "organizations": [],
    "locations": [],
    "technologies": []
  },
  "sentiment": "positif|negatif|netral",
  "complexity": "rendah|sedang|tinggi",
  "recommendations": ["saran1", "saran2"]
}

Jangan tambahkan field lain. Jangan beri penjelasan di luar JSON.
"""


def _slug(filename: str) -> str:
    name = Path(filename).stem
    return re.sub(r"[^\w]", "_", name)[:40]


def _word_count(text: str) -> int:
    return len(text.split())


def _extract_json(raw: str) -> dict:
    """Extract first JSON object from LLM response (handles markdown fences)."""
    # Strip ```json ... ``` fences if present
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    # Find outermost { }
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in LLM response")
    return json.loads(raw[start:end])


async def analyse_text(text: str, filename: str = "document.txt") -> tuple[str, Path | None]:
    """
    Analyse *text* with LLM and return (formatted_report, saved_json_path).
    json_path is None if saving failed.
    """
    wc = _word_count(text)

    # Truncate very long texts for LLM (keep first 6000 chars + last 1000)
    if len(text) > 8000:
        snippet = text[:6000] + "\n\n[... bagian tengah dipotong ...]\n\n" + text[-1000:]
    else:
        snippet = text

    llm = LLMClient()

    prompt = (
        f"Nama file: {filename}\n"
        f"Jumlah kata: {wc}\n\n"
        f"--- KONTEN ---\n{snippet}\n--- AKHIR ---"
    )

    try:
        raw = await llm.chat(
            [{"role": "user", "content": prompt}],
            system=_ANALYSIS_SYSTEM,
        )
        data = _extract_json(raw)
    except Exception as e:
        logger.error(f"Analysis LLM error: {e}")
        return (f"❌ Analisis gagal: `{e}`", None)

    # Inject word_count from local count (more reliable)
    data["word_count"] = wc
    data["filename"]   = filename
    data["analysed_at"] = datetime.now().isoformat(timespec="seconds")

    # ── Save JSON ──────────────────────────────────────────────────────────
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slug(filename)
    json_path = _OUT_DIR / f"{ts}_{slug}.json"
    try:
        json_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Failed to save analysis JSON: {e}")
        json_path = None

    # ── Format report ──────────────────────────────────────────────────────
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔍 ANALISIS DOKUMEN",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📄 File     : {filename}",
        f"📝 Kata     : {wc:,}",
        f"📂 Jenis    : {data.get('doc_type', '?')}",
        f"🌐 Bahasa   : {data.get('language', '?')}",
        f"🎭 Sentimen : {data.get('sentiment', '?')}",
        f"⚙️  Kompleks : {data.get('complexity', '?')}",
        "",
        "📋 RINGKASAN",
        data.get("summary", "-"),
        "",
    ]

    topics = data.get("topics", [])
    if topics:
        lines.append("🏷️  TOPIK UTAMA")
        for t in topics[:8]:
            lines.append(f"  • {t}")
        lines.append("")

    key_points = data.get("key_points", [])
    if key_points:
        lines.append("💡 POIN PENTING")
        for p in key_points[:10]:
            lines.append(f"  → {p}")
        lines.append("")

    entities = data.get("entities", {})
    ent_lines = []
    for label, key in [("👤 Orang", "people"), ("🏢 Organisasi", "organizations"),
                       ("📍 Lokasi", "locations"), ("🔧 Teknologi", "technologies")]:
        vals = entities.get(key, [])
        if vals:
            ent_lines.append(f"  {label}: {', '.join(str(v) for v in vals[:6])}")
    if ent_lines:
        lines.append("🔎 ENTITAS DITEMUKAN")
        lines.extend(ent_lines)
        lines.append("")

    recs = data.get("recommendations", [])
    if recs:
        lines.append("✅ REKOMENDASI")
        for r in recs[:5]:
            lines.append(f"  ▶ {r}")
        lines.append("")

    if json_path:
        lines.append(f"💾 Hasil disimpan: `{json_path.name}`")
        lines.append(f"   Path: `output/analysis/`")

    lines.append("")
    lines.append("💡 Gunakan /ppt untuk membuat presentasi dari file ini.")

    return ("\n".join(lines), json_path)
