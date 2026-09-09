"""
agents/paraphrase_agent.py — Human-like paraphrase / bypass AI-detection.

paraphrase_text(text, mode) → str

Modes:
  "normal"   — rewrite casually, preserve meaning, sound human
  "formal"   — rewrite in formal Indonesian/English, still human-authored feel
  "simple"   — simplify into short, easy sentences

Strategies applied:
  - Vary sentence length (mix short punchy + medium)
  - Use contractions and everyday vocabulary
  - Remove AI-signature phrases (e.g. "It's important to note", "Furthermore")
  - Start sentences with different words — no "The" + verb every time
  - Keep the original meaning intact, no new facts added
"""
from __future__ import annotations

import asyncio
import io
import logging
import re

import anthropic

import config

logger = logging.getLogger(__name__)

_SYSTEM_NORMAL = """Kamu adalah penulis manusia yang menulis ulang teks agar terdengar alami, personal, dan tidak seperti ditulis AI.

Aturan WAJIB:
1. Tulis ulang seluruh teks — jangan skip kalimat manapun.
2. Variasikan panjang kalimat: campur kalimat pendek (3-7 kata) dengan kalimat sedang.
3. Gunakan kosakata sehari-hari, hindari kata-kata formal berlebihan.
4. HAPUS frasa khas AI seperti: "Penting untuk dicatat", "Sebagai kesimpulan", "Furthermore", "It is worth noting", "In conclusion", "Notably", "It's important to", "delve into", "It should be noted".
5. Mulai variasi kalimat — jangan semua dimulai dengan "Ini" atau "The".
6. Boleh tambahkan kontraksi natural (e.g. "nggak", "bisa", "kita") jika Bahasa Indonesia.
7. Pertahankan makna dan fakta asli — JANGAN tambah informasi baru.
8. Output hanya teks hasil parafrasa — tanpa penjelasan, tanpa label, tanpa heading tambahan.
"""

_SYSTEM_FORMAL = """Kamu adalah penulis profesional yang menulis ulang teks agar terdengar formal namun tetap seperti ditulis manusia — bukan AI.

Aturan WAJIB:
1. Tulis ulang seluruh teks tanpa melewatkan bagian manapun.
2. Gunakan kalimat yang beragam panjangnya — hindari pola repetitif.
3. Pertahankan nada formal namun hindari frasa klise AI: "Penting untuk dicatat", "Sebagai simpulan", "Furthermore", "It is worth noting", "It is important to note".
4. Gunakan kata penghubung yang bervariasi — bukan hanya "Selain itu" atau "Namun".
5. Pertahankan semua fakta dan makna asli — tidak boleh menambah atau mengurangi informasi.
6. Output hanya teks hasil parafrasa — tanpa penjelasan atau komentar tambahan.
"""

_SYSTEM_SIMPLE = """Kamu adalah penulis yang menyederhanakan teks agar mudah dipahami siapa saja.

Aturan WAJIB:
1. Pecah kalimat panjang menjadi kalimat-kalimat pendek (max 15 kata per kalimat).
2. Ganti kata-kata sulit dengan padanan yang lebih umum.
3. Pertahankan semua informasi penting — jangan ada fakta yang hilang.
4. Hindari frasa AI yang kaku.
5. Output hanya teks yang sudah disederhanakan — tanpa penjelasan tambahan.
"""

_MODE_SYSTEM = {
    "normal": _SYSTEM_NORMAL,
    "formal": _SYSTEM_FORMAL,
    "simple": _SYSTEM_SIMPLE,
}

# Max chars sent to LLM in one call (avoid token overflow)
_CHUNK_SIZE = 3000


def _chunk_text(text: str, size: int = _CHUNK_SIZE) -> list[str]:
    """Split on paragraph boundaries to avoid mid-sentence cuts."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 1 > size and current:
            chunks.append(current.strip())
            current = para
        else:
            current = (current + "\n" + para).strip() if current else para
    if current:
        chunks.append(current.strip())
    return chunks or [text]


async def paraphrase_text(text: str, mode: str = "normal") -> str:
    """
    Paraphrase `text` using Claude Opus directly (best quality for human-like rewriting).
    Falls back to LLMClient (Groq/Ollama) if Anthropic key is not configured.
    Returns the rewritten text as a single string.
    """
    system_prompt = _MODE_SYSTEM.get(mode, _SYSTEM_NORMAL)
    chunks = _chunk_text(text)
    results: list[str] = []

    if config.ANTHROPIC_API_KEY:
        client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        model = config.ANTHROPIC_MODEL  # claude-opus-4-5 or whatever is set in .env

        for i, chunk in enumerate(chunks):
            logger.info(f"Paraphrasing chunk {i+1}/{len(chunks)} via Claude {model} (mode={mode})")
            user_msg = f"Tulis ulang teks berikut:\n\n{chunk}"
            try:
                response = await asyncio.wait_for(
                    client.messages.create(
                        model=model,
                        max_tokens=4096,
                        system=system_prompt,
                        messages=[{"role": "user", "content": user_msg}],
                    ),
                    timeout=120.0,
                )
                results.append(response.content[0].text.strip())
            except Exception as e:
                logger.error(f"Claude paraphrase chunk {i+1} failed: {e}")
                raise
    else:
        # Fallback to default LLM chain (Groq/Ollama)
        from llm.client import LLMClient
        llm = LLMClient()
        for i, chunk in enumerate(chunks):
            logger.info(f"Paraphrasing chunk {i+1}/{len(chunks)} via fallback LLM (mode={mode})")
            user_msg = f"Tulis ulang teks berikut:\n\n{chunk}"
            try:
                result = await llm.chat(
                    messages=[{"role": "user", "content": user_msg}],
                    system=system_prompt,
                )
                results.append(result.strip())
            except Exception as e:
                logger.error(f"Paraphrase chunk {i+1} failed: {e}")
                raise

    return "\n\n".join(results)


# ── DOCX builder with English-italic formatting ───────────────────────────────

# Indonesian stop words — presence of ANY of these → sentence is Indonesian
_ID_STOP = frozenset({
    "yang", "dan", "di", "ke", "dari", "ada", "ini", "itu", "dengan",
    "untuk", "tidak", "sudah", "akan", "bisa", "juga", "pada", "dalam",
    "adalah", "atau", "oleh", "saya", "kamu", "kami", "mereka", "anda",
    "kita", "telah", "saat", "ketika", "karena", "sehingga", "namun",
    "tetapi", "jika", "maka", "tersebut", "bahwa", "hal", "cara", "dapat",
    "harus", "lebih", "sangat", "setiap", "sebagai", "antara", "selain",
    "sedangkan", "belum", "agar", "hingga", "maupun", "setelah", "sebelum",
    "salah", "satu", "dua", "tiga", "tentang", "juga", "sudah", "belum",
    "nya", "pun", "lah", "saja", "pula", "pernah", "masih", "memang",
    "kalau", "seperti", "semua", "beberapa", "banyak", "sedikit", "lain",
    "diri", "mereka", "ia", "dia", "kami", "mereka", "apa", "siapa",
    "dimana", "kapan", "bagaimana", "mengapa", "kenapa", "apakah",
})


def _is_english(sentence: str) -> bool:
    """Return True if sentence is likely English (not Indonesian/other)."""
    words = re.findall(r'\b[a-zA-Z]+\b', sentence.lower())
    if not words:
        return False
    # Any Indonesian stop word → not English
    if any(w in _ID_STOP for w in words):
        return False
    # Mostly ASCII alphabetic chars → likely English
    alpha = sum(c.isalpha() for c in sentence)
    if alpha == 0:
        return False
    ascii_alpha = sum(c.isalpha() and ord(c) < 128 for c in sentence)
    return (ascii_alpha / alpha) > 0.85


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, preserving trailing whitespace."""
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    result = []
    for i, part in enumerate(parts):
        result.append(part + (" " if i < len(parts) - 1 else ""))
    return result


def build_paraphrase_docx(
    paraphrased_text: str,
    original_docx_bytes: bytes | None = None,
) -> bytes:
    """
    Build a formatted DOCX from paraphrased text.

    - Preserves heading/body structure from original DOCX when provided.
    - English sentences are set to italic.
    - Returns raw bytes of the .docx file.
    """
    from docx import Document
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa

    # Build a fresh document (avoid inheriting unwanted content from original)
    doc = Document()

    # Copy default font from original if available
    orig_font_name = None
    orig_font_size = None
    if original_docx_bytes:
        try:
            orig = Document(io.BytesIO(original_docx_bytes))
            default_style = orig.styles["Normal"]
            orig_font_name = default_style.font.name
            orig_font_size = default_style.font.size
        except Exception:
            pass

    if orig_font_name:
        doc.styles["Normal"].font.name = orig_font_name
    if orig_font_size:
        doc.styles["Normal"].font.size = orig_font_size

    paragraphs = [p.strip() for p in paraphrased_text.split("\n\n") if p.strip()]

    for para_text in paragraphs:
        words = para_text.split()
        # Heuristic: treat as heading if short, no trailing period, all on one line
        is_heading = (
            len(words) <= 12
            and len(para_text) < 100
            and not para_text.endswith(".")
            and "\n" not in para_text
        )

        if is_heading:
            para = doc.add_paragraph(style="Heading 2")
            run = para.add_run(para_text)
            run.bold = True
            if _is_english(para_text):
                run.italic = True
        else:
            para = doc.add_paragraph(style="Normal")
            sentences = _split_sentences(para_text)
            for sentence in sentences:
                if not sentence.strip():
                    continue
                run = para.add_run(sentence)
                if _is_english(sentence):
                    run.italic = True

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()
