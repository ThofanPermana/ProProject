"""
bot/telegram_bot.py — Telegram command & message handlers for Hermes.

Commands:
  /start   — welcome message
  /help    — list all commands
  /ppt     — build a Gamma presentation (topic typed inline, or upload a file)
  /model   — show current LLM backend
  /clear   — wipe this user's chat memory

Any non-command message → HermesAgent.chat()
Document upload without /ppt → prompt user to use /ppt
Supported file types: .txt, .pdf, .docx
"""
from __future__ import annotations

import io
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agents.analysis_agent import analyse_text
from agents.gptzero_agent import check_gptzero
from agents.hermes_agent import HermesAgent
from agents.paraphrase_agent import paraphrase_text, build_paraphrase_docx
from agents.image_agent import analyze_image, generate_image, edit_image, image_to_video
from agents.scanner_agent import dns_lookup, dirscan_target, api_scan, aiscan_target, \
    exa_find_cms_sites, auto_scan_cms, CMS_SIGNATURES, scan_target
from agents.scraper_agent import (
    is_url_or_domain,
    scrape_and_format,
    crawl_and_format,
    search_entity,
    list_datasets,
    search_dataset,
    show_dataset,
)
from memory.dataset_logger import get_stats as dataset_stats

logger = logging.getLogger(__name__)

# Shared agent instance (single process, thread-safe enough for polling)
_agent = HermesAgent()

HELP_TEXT = """
*Hermes — AI Agent* 🤖

*Commands:*
• /start — welcome
• /help — this message
• /ppt \\<topic\\> — generate a presentation on any topic
• /ppt — (then upload a .txt/.pdf/.docx file) — use file content as input
• /analys — analisis dokumen dengan AI \\(ringkasan, topik, entitas, sentimen\\) — lalu upload file
  _Hasil disimpan ke `output/analysis/` \\(.json\\)_
• /parafrase \\<teks\\> — tulis ulang teks agar tidak terlihat seperti AI \\(mode: normal/formal/simple\\)
• /parafrase — lalu upload file .txt/.pdf/.docx untuk parafrasa otomatis seluruh dokumen
  _Hasil dikembalikan sebagai .docx dengan teks Inggris di-italic_
• /gptzero \\<teks\\> — cek apakah teks ditulis AI \\(GPTZero AI detector\\)
• /gptzero — lalu upload file untuk deteksi AI otomatis
• /model — show current LLM backend
• /clear — forget this session's conversation

*Sessions:*
• /sessions — list all your sessions
• /newsession \\[name\\] — start a new session
• /switch \\<name or number\\> — switch to a session
• /rename \\<new name\\> — rename current session
• /delsession \\<name or number\\> — delete a session

*Web & Security:*
• /search \\<query\\> — search the web and get a summary
• /browse \\<url\\> — open and summarise any webpage
• /scan \\<url/domain\\> — full security scan \\(ports, SSL, headers, sensitive paths, cookies, subdomains\\)
  _Disimpan → `output/scans/scan/` \\(.json \\+ .txt\\)_
  _atau ketik: "cek keamanan website.com" / "scan ulang"_
• /bulkscan — scan banyak domain sekaligus via file .txt \\(satu domain per baris\\)
  _Kirim /bulkscan lalu upload file .txt berisi daftar URL/domain_
  _Disimpan → `output/scans/bulkscan/`_
• /dirscan \\<url\\> — directory & path enumeration \\(temukan folder/file tersembunyi\\)
• /dirscan \\<url\\> \\-\\-api — fokus ke API endpoints
• /dirscan \\<url\\> \\-\\-deep — wordlist lebih besar \\(\\~300 paths\\)
  _Disimpan → `output/scans/dirscan/`_
• /apiscan \\<url\\> — deteksi jenis API: GraphQL, REST, SOAP, JSON\\-RPC, gRPC, OData, WebSocket
  _Disimpan → `output/scans/apiscan/`_
• /aiscan \\<url\\> — AI\\-guided iterative scan \\(Groq generate probe paths per round\\)
  _Disimpan → `output/scans/aiscan/`_
• /cmsscan \\<cms\\> \\[jumlah\\] \\[topik\\] \\[negara:XX\\] — cari \\+ scan website dengan CMS tertentu via Exa auto\\-discovery
  _CMS: WordPress, WooCommerce, Joomla, Drupal, Magento, PrestaShop, OpenCart, Shopify, Wix, Squarespace_
  _Contoh: /cmsscan shopify 5 shoes negara:id | /cmsscan magento 10 electronics negara:br_
  _Kode negara: id, my, sg, us, br, de, fr, jp, au, dsb\\. | Output → output/scans/cms\\-autoscan/_
• /dns \\<domain\\> — DNS-only lookup: A, AAAA, MX, NS, TXT, CNAME, SOA, DMARC \\(cepat, tanpa HTTP scan\\)

*Knowledge Base (RAG):*
• /upload — upload a .txt/.pdf to your personal knowledge base
• /raglist — list your indexed documents
• /ragclear — clear your knowledge base

*Dataset (Training):*
• /datastats — lihat berapa data interaksi yang sudah terkumpul

*Images:*
• Kirim foto saja → analisis & deskripsikan gambar
• Kirim foto \\+ caption → edit gambar sesuai instruksi \\(otomatis\\)
• /editimg — panduan lengkap cara edit gambar dengan AI \\(hapus watermark, ganti background, ubah style, dsb\\)
  _Gunakan Claude Opus untuk hasil terbaik_
• /generate \\<prompt\\> — buat gambar baru dari teks
• /video \\<motion prompt\\> — balas foto untuk animasikan jadi video \\(fal\\.ai\\)

*Data & Scraping:*
• /scrape \\<url\\> — ambil data dari halaman web (tabel, list, teks)
• /scrape \\<url\\> \\-\\-save — ambil + simpan ke file lokal \\(hemat token\\)
• /crawl \\<url\\> — crawl situs, ikuti semua link internal secara otomatis
• /crawl \\<url\\> \\-\\-depth 3 \\-\\-max 20 \\-\\-save — crawl lebih dalam \\+ simpan
• /datalist — lihat semua dataset lokal yang sudah disimpan
• /datasearch \\<file\\> \\<query\\> — cari data di dataset lokal
• /datashow \\<file\\> — tampilkan isi dataset lokal

*Chat:*
Just send any message and I'll reply.
""".strip()


# ── /start ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or "there"
    await update.message.reply_text(
        f"Hey {name}! I'm *Hermes*, your AI assistant. ⚡\n\n"
        "Ask me anything, or use /ppt to generate a presentation.\n"
        "Type /help for the full command list.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /help ─────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


# ── /model ────────────────────────────────────────────────────────────────

async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /model          — show active LLM backend
    /model claude   — switch primary to Claude (Anthropic)
    /model groq     — switch primary to Groq
    /model ollama   — switch primary to Ollama
    """
    if not update.message:
        return
    arg = (context.args[0].lower() if context.args else "").strip()
    if arg in ("claude", "groq", "ollama", "anthropic"):
        ok = _agent.set_preferred(arg)
        if ok:
            await update.message.reply_text(
                f"✅ Primary LLM switched to *{_agent.backend_name.split(' [')[0]}*",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                f"❌ Backend `{arg}` not available — check API keys in .env",
                parse_mode=ParseMode.MARKDOWN,
            )
        return
    await update.message.reply_text(
        f"*Active LLM backend:*\n`{_agent.backend_name}`\n\n"
        f"Switch: `/model claude` · `/model groq` · `/model ollama`",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /sessions ─────────────────────────────────────────────────────────────

async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    sessions, active = _agent.list_sessions(user_id)
    lines = ["*Your sessions:*"]
    for i, s in enumerate(sessions, 1):
        marker = "▶" if s["id"] == active else "  "
        lines.append(f"{marker} `{i}.` {s['name']} — _{s.get('last_used', '')}_ ")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_newsession(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    name = " ".join(context.args).strip() if context.args else None
    name = _agent.new_session(user_id, name)
    await update.message.reply_text(
        f"✅ Started new session: *{name}*\nThis is a fresh conversation.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    ref = " ".join(context.args).strip() if context.args else ""
    if not ref:
        await update.message.reply_text("Usage: `/switch <name or number>`",
                                        parse_mode=ParseMode.MARKDOWN)
        return
    name = _agent.switch_session(user_id, ref)
    if name is None:
        await update.message.reply_text(f"Session `{ref}` not found. Use /sessions to list them.",
                                        parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(f"✅ Switched to *{name}*", parse_mode=ParseMode.MARKDOWN)


async def cmd_rename(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    name = " ".join(context.args).strip() if context.args else ""
    if not name:
        await update.message.reply_text("Usage: `/rename <new name>`",
                                        parse_mode=ParseMode.MARKDOWN)
        return
    final = _agent.rename_session(user_id, name)
    await update.message.reply_text(f"✅ Renamed to *{final}*", parse_mode=ParseMode.MARKDOWN)


async def cmd_delsession(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    ref = " ".join(context.args).strip() if context.args else ""
    if not ref:
        await update.message.reply_text("Usage: `/delsession <name or number>`",
                                        parse_mode=ParseMode.MARKDOWN)
        return
    deleted = _agent.delete_session(user_id, ref)
    if deleted is None:
        await update.message.reply_text(
            f"Cannot delete `{ref}` — not found or it's your only session.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(f"🗑️ Deleted session *{deleted}*", parse_mode=ParseMode.MARKDOWN)


# ── /clear ────────────────────────────────────────────────────────────────

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    name = _agent.clear_memory(user_id)
    await update.message.reply_text(f"Memory cleared for *{name}*. Starting fresh! 🗑️",
                                    parse_mode=ParseMode.MARKDOWN)


# ── /ppt ──────────────────────────────────────────────────────────────────

async def cmd_ppt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    topic = " ".join(context.args).strip() if context.args else ""

    # If there's a pending uploaded file, use it
    pending = context.user_data.pop("pending_text", "")
    pending_fn = context.user_data.pop("pending_filename", "document.txt")
    if pending:
        await _run_ppt(update, user_id, pending[:4000])
        return

    if not topic:
        context.user_data["ppt_mode"] = True
        await update.message.reply_text(
            "Please provide a topic after /ppt, e.g.:\n"
            "`/ppt The Future of Renewable Energy`\n\n"
            "Or upload a `.txt`/`.pdf`/`.docx` file now and I'll use its content.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await _run_ppt(update, user_id, topic)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    File upload router:
      • /upload flag in user_data → index into RAG knowledge base
      • /ppt flag or default      → use as PPT input
    Supported: .txt, .pdf, .docx
    """
    doc = update.message.document
    if not doc:
        return

    mime = doc.mime_type or ""
    filename = doc.file_name or ""
    is_docx = (
        "wordprocessingml" in mime
        or "msword" in mime
        or filename.lower().endswith(".docx")
    )
    is_text = "text" in mime or filename.lower().endswith(".txt")
    is_pdf  = "pdf" in mime or filename.lower().endswith(".pdf")

    if not (is_text or is_pdf or is_docx):
        await update.message.reply_text(
            "Please upload a .txt, .pdf, or .docx file.\n"
            "Or type your topic directly with /ppt."
        )
        return

    await update.message.reply_text("📂 Reading your file\u2026 ⏳")
    file = await context.bot.get_file(doc.file_id)
    raw: bytes = bytes(await file.download_as_bytearray())

    try:
        if is_docx:
            import io as _io
            from docx import Document as _DocxDocument
            _buf = _io.BytesIO(raw)
            _doc = _DocxDocument(_buf)
            text = "\n".join(p.text for p in _doc.paragraphs if p.text.strip())
        else:
            text = raw.decode("utf-8", errors="replace")
        text = text.strip()
    except Exception as e:
        await update.message.reply_text(f"Could not read file: {e}")
        return

    if not text:
        await update.message.reply_text("The file appears to be empty.")
        return

    user_id  = update.effective_user.id
    filename = doc.file_name or ("document.docx" if is_docx else "document.txt")

    # Check if we're in bulk-scan mode (set by /bulkscan command)
    if context.user_data.pop("bulkscan_mode", False):
        if not is_text:
            await update.message.reply_text("Hanya file .txt yang didukung untuk bulk scan.")
            return
        lines = text.splitlines()
        targets = [
            ln.strip() for ln in lines
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if not targets:
            await update.message.reply_text("File kosong atau tidak ada target yang valid.")
            return
        # Cap at 50 targets
        if len(targets) > 50:
            await update.message.reply_text(
                f"⚠️ File berisi {len(targets)} target. Hanya 50 pertama yang akan di-scan."
            )
            targets = targets[:50]

        total = len(targets)
        import os as _os, json as _json, datetime as _dt
        save_dir = _os.path.join(str(_os.path.dirname(__file__).replace("bot", "")), "output", "scans", "bulkscan")
        _os.makedirs(save_dir, exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_path = _os.path.join(save_dir, f"summary_{ts}.txt")

        status_msg = await update.message.reply_text(
            f"🔍 Bulk Scan dimulai: *{total}* target\n"
            f"Harap tunggu, proses berjalan…",
            parse_mode=ParseMode.MARKDOWN,
        )
        results_text: list[str] = []
        for idx, tgt in enumerate(targets, 1):
            try:
                await status_msg.edit_text(
                    f"🔍 Bulk Scan [{idx}/{total}]\nScanning: `{tgt}`…",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass
            try:
                result = await scan_target(tgt)
                if result.get("error"):
                    line = f"[{idx}/{total}] ❌ {tgt} — {result['error']}"
                else:
                    sev = result.get("severity_summary", {})
                    c = sev.get("KRITIS", 0)
                    h = sev.get("TINGGI", 0)
                    m = sev.get("SEDANG", 0)
                    l = sev.get("RENDAH", 0)
                    waf = result.get("waf", "")
                    waf_tag = f" [WAF: {waf}]" if waf else ""
                    line = f"[{idx}/{total}] ✅ {tgt}{waf_tag} — C:{c} H:{h} M:{m} L:{l}"
                    # Save individual JSON
                    safe = tgt.replace("https://", "").replace("http://", "").replace("/", "_")
                    jpath = _os.path.join(save_dir, f"scan_{safe}_{ts}.json")
                    try:
                        with open(jpath, "w", encoding="utf-8") as _f:
                            _json.dump(result, _f, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
            except Exception as e:
                line = f"[{idx}/{total}] ❌ {tgt} — Exception: {e}"
            results_text.append(line)
            logger.info(f"bulkscan {line}")

        # Write summary file
        try:
            with open(summary_path, "w", encoding="utf-8") as _sf:
                _sf.write(f"Bulk Scan — {ts}\n")
                _sf.write(f"File: {filename}\n")
                _sf.write(f"Total targets: {total}\n\n")
                _sf.write("\n".join(results_text))
        except Exception:
            pass

        await status_msg.delete()
        header = f"✅ *Bulk Scan Selesai* — {total} target\n\n"
        body = "\n".join(results_text)
        full = header + f"`{body}`\n\nSummary disimpan ke `output/scans/bulkscan/`"
        for chunk in _split(full, 4096):
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN,
                                            disable_web_page_preview=True)
        # Send summary .txt as document
        if _os.path.exists(summary_path):
            try:
                with open(summary_path, "rb") as _sf:
                    await update.message.reply_document(
                        document=_sf,
                        filename=_os.path.basename(summary_path),
                        caption=f"📋 Bulk Scan summary — {total} target dari {filename}",
                    )
            except Exception as _e:
                logger.warning(f"Could not send bulkscan summary: {_e}")
        return

    # Check if we're in RAG-upload mode (set by /upload command)
    upload_mode = context.user_data.pop("upload_mode", False)

    if upload_mode:
        await update.message.chat.send_action(ChatAction.TYPING)
        try:
            reply = await _agent.handle_upload(user_id, filename, text)
        except Exception as e:
            logger.error(f"RAG upload failed: {e}")
            await update.message.reply_text(f"Upload failed: `{e}`", parse_mode=ParseMode.MARKDOWN)
            return
        await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
    elif context.user_data.pop("analys_mode", False):
        # /analys was issued before upload
        await _run_analys(update, context, text, filename)
    elif context.user_data.pop("ppt_mode", False):
        # /ppt was issued before upload
        await _run_ppt(update, user_id, text[:4000])
    elif context.user_data.pop("parafrase_mode", False):
        # /parafrase was issued before upload
        mode = context.user_data.pop("parafrase_submode", "normal")
        docx_bytes = raw if is_docx else None
        await _run_parafrase(update, text, filename, mode, original_docx_bytes=docx_bytes)
    elif context.user_data.pop("gptzero_mode", False):
        # /gptzero was issued before upload
        await _run_gptzero(update, text)
    else:
        # No mode set — store pending text and ask user what to do
        context.user_data["pending_text"]     = text
        context.user_data["pending_filename"] = filename
        wc = len(text.split())
        await update.message.reply_text(
            f"📂 *{filename}* diterima ({wc:,} kata)\n\n"
            f"Pilih tindakan:\n"
            f"• /analys — analisis konten file dengan AI\n"
            f"• /parafrase — tulis ulang agar tidak terlihat seperti AI\n"
            f"• /gptzero — cek kandungan AI di dokumen ini\n"
            f"• /ppt — buat presentasi dari file ini\n"
            f"• /upload — simpan ke knowledge base (RAG)",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _run_ppt(update: Update, user_id: int, topic: str) -> None:
    """Shared presentation generation flow."""
    await update.message.reply_text(
        f"Building presentation for:\n*{topic[:120]}*\n\nThis may take ~1–2 minutes… ⏳",
        parse_mode=ParseMode.MARKDOWN,
    )
    await update.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)

    try:
        result = await _agent.handle_ppt(user_id, topic)
    except Exception as e:
        logger.error(f"PPT generation failed: {e}")
        await update.message.reply_text(f"Presentation generation failed:\n`{e}`",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    gamma_url = result.get("gamma_url", "")
    pdf_path = result.get("pdf_path")
    pptx_path = result.get("pptx_path")
    credits = result.get("credits_remaining", "?")

    # Send URL first
    reply_lines = [f"✅ *Presentation ready!*"]
    if gamma_url:
        reply_lines.append(f"🔗 [View on Gamma]({gamma_url})")
    reply_lines.append(f"Credits remaining: `{credits}`")
    await update.message.reply_text("\n".join(reply_lines), parse_mode=ParseMode.MARKDOWN)

    # Send PDF
    if pdf_path:
        try:
            with open(pdf_path, "rb") as f:
                await update.message.reply_document(document=f, filename="presentation.pdf",
                                                    caption="📄 PDF version")
        except Exception as e:
            logger.warning(f"Failed to send PDF: {e}")

    # Send PPTX
    if pptx_path:
        try:
            with open(pptx_path, "rb") as f:
                await update.message.reply_document(document=f, filename="presentation.pptx",
                                                    caption="📊 PowerPoint version")
        except Exception as e:
            logger.warning(f"Failed to send PPTX: {e}")

async def _run_analys(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    filename: str,
) -> None:
    """Run analysis on text and send report."""
    status = await update.message.reply_text(
        f"🔍 Menganalisis *{filename}*… ⏳\n_Mohon tunggu, AI sedang membaca dokumen._",
        parse_mode=ParseMode.MARKDOWN,
    )
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        report, json_path = await analyse_text(text, filename)
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        await status.edit_text(f"❌ Analisis gagal: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return
    await status.delete()
    for chunk in _split(report, 4096):
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)


# ── /gptzero ─────────────────────────────────────────────────────────────────

async def cmd_gptzero(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /gptzero <text>  — check inline text for AI content
    /gptzero         — then upload a file to scan the document
    """
    if not update.message:
        return

    inline_text = " ".join(context.args).strip() if context.args else ""

    # Use pending file if available
    pending = context.user_data.pop("pending_text", "")
    context.user_data.pop("pending_filename", None)
    if pending:
        await _run_gptzero(update, pending)
        return

    if inline_text:
        await _run_gptzero(update, inline_text)
        return

    context.user_data["gptzero_mode"] = True
    await update.message.reply_text(
        "🔍 *GPTZero AI Detector*\n\n"
        "Ketik teks setelah perintah, atau upload file `.txt`/`.pdf`/`.docx` sekarang.\n\n"
        "*Contoh:*\n"
        "`/gptzero Teks yang ingin dicek...`\n"
        "`/gptzero` - lalu upload file",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _run_gptzero(update: Update, text: str) -> None:
    wc = len(text.split())
    status = await update.message.reply_text(
        f"🔍 Memeriksa {wc:,} kata dengan GPTZero… ⏳",
    )
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        report, score = await check_gptzero(text)
    except Exception as e:
        logger.error(f"GPTZero check failed: {e}")
        await status.edit_text(f"❌ GPTZero gagal: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return
    await status.delete()
    for chunk in _split(report, 4096):
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk)


# ── /parafrase ───────────────────────────────────────────────────────────────

async def cmd_parafrase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /parafrase <text>          — paraphrase inline text (normal mode)
    /parafrase formal <text>   — formal rewrite
    /parafrase simple <text>   — simplify into short sentences
    /parafrase                 — then upload a file to paraphrase the whole document
    """
    if not update.message:
        return

    args = list(context.args) if context.args else []

    # Parse optional mode prefix
    mode = "normal"
    if args and args[0].lower() in ("normal", "formal", "simple"):
        mode = args[0].lower()
        args = args[1:]

    inline_text = " ".join(args).strip()

    # If pending file available, use it immediately
    pending = context.user_data.pop("pending_text", "")
    pending_fn = context.user_data.pop("pending_filename", "document.txt")
    if pending:
        await _run_parafrase(update, pending, pending_fn, mode)
        return

    if inline_text:
        await _run_parafrase(update, inline_text, "<inline>", mode)
        return

    # No text — ask user to upload a file
    context.user_data["parafrase_mode"] = True
    context.user_data["parafrase_submode"] = mode
    await update.message.reply_text(
        "✍️ *Parafrase Dokumen*\n\n"
        f"Mode: `{mode}`\n\n"
        "Kirimkan teks langsung setelah perintah, atau upload file `.txt`/`.pdf`/`.docx` sekarang.\n\n"
        "*Contoh:*\n"
        "`/parafrase Kecerdasan buatan adalah teknologi...`\n"
        "`/parafrase formal` - lalu upload file\n"
        "`/parafrase simple` - lalu upload file",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _run_parafrase(
    update: Update,
    text: str,
    source_name: str,
    mode: str = "normal",
    original_docx_bytes: bytes | None = None,
) -> None:
    """Core paraphrase flow — works for both inline text and uploaded files."""
    wc = len(text.split())
    label = source_name if source_name != "<inline>" else "teks"
    safe_label = label.replace("_", "\\_").replace("*", "\\*")
    status = await update.message.reply_text(
        f"✍️ Menulis ulang *{safe_label}* ({wc:,} kata, mode: `{mode}`)… ⏳\n"
        f"_Mohon tunggu._",
        parse_mode=ParseMode.MARKDOWN,
    )
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        result = await paraphrase_text(text, mode)
    except Exception as e:
        logger.error(f"Paraphrase failed: {e}")
        await status.edit_text(f"❌ Parafrasa gagal: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    await status.delete()

    # Send text preview in chat (first 4096 chars)
    for chunk in _split(result, 4096):
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk)

    # For documents (file upload, ≥500 words), also send as .docx with italic English
    if wc >= 500 and source_name != "<inline>":
        try:
            docx_bytes = build_paraphrase_docx(result, original_docx_bytes)
            stem = source_name.rsplit(".", 1)[0] if "." in source_name else source_name
            fname = f"{stem}_parafrase.docx"
            await update.message.reply_document(
                document=io.BytesIO(docx_bytes),
                filename=fname,
                caption=(
                    f"📄 *{fname}*\n"
                    f"Mode: `{mode}` • {wc:,} kata asli\n"
                    f"_Teks bahasa Inggris diformat italic_"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.warning(f"DOCX build failed: {e}")
            await update.message.reply_text(f"⚠️ Gagal buat DOCX: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ── /analys ───────────────────────────────────────────────────────────────────

async def cmd_analys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Analyse an uploaded file or pending text with AI. No PPT/Gamma involved."""
    if not update.message:
        return

    # If there's a pending uploaded file waiting, use it immediately
    pending = context.user_data.pop("pending_text", "")
    pending_fn = context.user_data.pop("pending_filename", "document.txt")
    if pending:
        await _run_analys(update, context, pending, pending_fn)
        return

    # Otherwise set mode and ask user to upload
    context.user_data["analys_mode"] = True
    await update.message.reply_text(
        "🔍 *Analisis Dokumen*\n\n"
        "Kirimkan file `.txt`, `.pdf`, atau `.docx` sekarang.\n"
        "AI akan menganalisis isinya dan memberikan:\n"
        "  • Ringkasan\n"
        "  • Topik utama\n"
        "  • Poin penting\n"
        "  • Entitas (orang, organisasi, lokasi, teknologi)\n"
        "  • Sentimen & kompleksitas\n"
        "  • Rekomendasi\n"
        "  • Hasil tersimpan sebagai JSON di `output/analysis/`",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /video ───────────────────────────────────────────────────────────────────────

async def cmd_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Usage: Reply to a photo with /video <motion description>
    Motion description is REQUIRED — describes how the image should move.
    Optional: prefix with duration in seconds (5 or 10), e.g. /video 10 slow zoom out
    """
    args = context.args or []
    # Check if first arg is a duration (5 or 10)
    duration = 5
    if args and args[0] in ("5", "10"):
        duration = int(args[0])
        args = args[1:]
    prompt = " ".join(args).strip()

    # Find the photo — either the replied-to message or the current message
    photo_msg = update.message.reply_to_message if update.message.reply_to_message else update.message
    if not photo_msg or not photo_msg.photo:
        await update.message.reply_text(
            "⚠️ *How to use /video:*\n"
            "1\\. Send or forward a photo to this chat\n"
            "2\\. Reply to that photo with `/video <motion description>`\n\n"
            "*Examples:*\n"
            "`/video hair blowing in the wind`\n"
            "`/video slow zoom out, clouds drifting`\n"
            "`/video camera pans right, waves crashing`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # Require a motion prompt
    if not prompt:
        await update.message.reply_text(
            "✏️ *Motion description required\\!*\n\n"
            "Reply to the photo again with a description of the motion:\n"
            "`/video hair blowing in the wind`\n"
            "`/video slow zoom in, bokeh`\n"
            "`/video camera dolly shot, cinematic`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    await update.message.chat.send_action(ChatAction.RECORD_VIDEO)
    status = await update.message.reply_text(
        f"🎬 Animating _{prompt}_ \\({duration}s\\)… \\(30–90 s\\)",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    try:
        photo = photo_msg.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        img_bytes: bytes = await file.download_as_bytearray()
        video_bytes = await image_to_video(img_bytes, prompt=prompt, duration=duration)
    except RuntimeError as e:
        await status.edit_text(f"⚠️ {e}")
        return
    except Exception as e:
        logger.error(f"image_to_video failed: {e}")
        await status.edit_text(f"Video generation failed: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    await status.delete()
    await update.message.reply_video(
        video=io.BytesIO(video_bytes),
        caption=f"🎬 {prompt}",
        supports_streaming=True,
    )
# ── /dns ─────────────────────────────────────────────────────────────────

async def cmd_dns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /dns <domain>
    Query DNS records only: A, AAAA, MX, NS, TXT, CNAME, DMARC.
    """
    if not update.message:
        return
    target = " ".join(context.args).strip() if context.args else ""
    if not target:
        await update.message.reply_text(
            "Usage: /dns <domain>\n\nContoh:\n/dns example.com\n/dns unpak.ac.id\n\n"
            "Queries: A, AAAA, MX, NS, TXT (SPF), CNAME, SOA, DMARC"
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)
    status_msg = await update.message.reply_text(f"Querying DNS for {target}...")
    try:
        report = await dns_lookup(target)
    except Exception as e:
        logger.error(f"DNS lookup failed for {target}: {e}")
        await status_msg.edit_text(f"DNS lookup gagal: {e}")
        return
    await status_msg.delete()
    for chunk in _split(report, 4096):
        await update.message.reply_text(chunk)


# ── /scan ────────────────────────────────────────────────────────────────

async def cmd_bulkscan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /bulkscan
    Set mode to accept a .txt file containing one URL/domain per line,
    then scan each target sequentially.
    """
    if not update.message:
        return
    context.user_data["bulkscan_mode"] = True
    await update.message.reply_text(
        "📋 *Bulk Scan*\n\n"
        "Kirim file `.txt` berisi daftar URL atau domain — satu per baris.\n\n"
        "Contoh isi file:\n"
        "```\n"
        "example.com\n"
        "https://target.site\n"
        "shop.another.id\n"
        "```\n"
        "Baris kosong dan baris yang diawali `#` akan dilewati.\n"
        "Maks *50 target* per file.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /scan <url or domain>
    Run a full security scan: headers, SSL, ports, sensitive paths, cookies, etc.
    """
    if not update.message:
        return
    target = " ".join(context.args).strip() if context.args else ""
    if not target:
        await update.message.reply_text(
            "*🔍 Security Scanner*\n\n"
            "Usage: `/scan <url atau domain>`\n\n"
            "Contoh:\n"
            "`/scan example.com`\n"
            "`/scan https://target.go.id`\n\n"
            "Checks: Port scan, SSL/TLS, HTTP headers, cookie flags, "
            "sensitive paths (/.env, /.git, /admin, dll), server info leakage.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)
    status_msg = await update.message.reply_text(
        f"🔍 Scanning `{target}`…\n"
        f"Checking ports, SSL, headers, sensitive paths — harap tunggu ±30 detik.",
        parse_mode=ParseMode.MARKDOWN,
    )

    user_id = update.effective_user.id
    try:
        report, txt_path = await _agent.handle_scan(user_id, target)
    except Exception as e:
        logger.error(f"Scan failed for {target}: {e}")
        await status_msg.edit_text(f"Scan gagal: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    # Remember target for "scan ulang" plain-text trigger
    context.user_data["last_scan_target"] = target

    await status_msg.delete()
    # Send as plain text — report contains dynamic content that may break Markdown
    for chunk in _split(report, 4096):
        await update.message.reply_text(chunk, disable_web_page_preview=True)
    # Send the saved report as a file attachment
    try:
        import os as _os
        if txt_path and _os.path.exists(str(txt_path)):
            with open(str(txt_path), "rb") as _f:
                await update.message.reply_document(
                    document=_f,
                    filename=_os.path.basename(str(txt_path)),
                    caption=f"📄 Scan report: {target}",
                )
    except Exception as _e:
        logger.warning(f"Could not send scan file: {_e}")


# ── /datastats ────────────────────────────────────────────────────────────────

async def cmd_datastats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    stats = dataset_stats()
    total = stats.get("total", 0)
    by_type = stats.get("by_type", {})
    lines = [
        "📊 *Dataset Training — Auto-collected*\n",
        f"Total records: `{total}`",
    ]
    for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
        icon = {"chat": "💬", "search": "🔍", "browse": "🌐", "upload": "📎"}.get(t, "•")
        lines.append(f"{icon} {t}: `{count}`")
    lines.append(f"\nFile: `tools/auto_dataset.jsonl`")
    lines.append("Gunakan `python tools/build_dataset.py` untuk merge semua data ke dataset final.")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

# ── /upload ──────────────────────────────────────────────────────────────────

async def cmd_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set upload mode then ask the user to send the file."""
    # If there's a pending file, index it directly
    pending = context.user_data.pop("pending_text", "")
    pending_fn = context.user_data.pop("pending_filename", "document.txt")
    if pending:
        user_id = update.effective_user.id
        await update.message.chat.send_action(ChatAction.TYPING)
        try:
            reply = await _agent.handle_upload(user_id, pending_fn, pending)
        except Exception as e:
            logger.error(f"RAG upload failed: {e}")
            await update.message.reply_text(f"Upload failed: `{e}`", parse_mode=ParseMode.MARKDOWN)
            return
        await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
        return

    context.user_data["upload_mode"] = True
    await update.message.reply_text(
        "📎 *Upload to Knowledge Base*\n\n"
        "Send me a `.txt` or `.pdf` file now and I will index it.\n"
        "After indexing, I will automatically use it when you ask related questions.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /raglist ─────────────────────────────────────────────────────────────────

async def cmd_raglist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    docs = _agent.rag_list(user_id)
    if not docs:
        await update.message.reply_text(
            "Your knowledge base is empty.\nUse /upload to add documents."
        )
        return
    lines = ["📚 *Your Knowledge Base:*\n"]
    for i, d in enumerate(docs, 1):
        embed_tag = "✅" if d.get("has_embeddings") else "🔤"
        lines.append(
            f"{i}. {embed_tag} *{d['filename']}* — {d['chunks']} chunks\n"
            f"   `{d['doc_id']}` | added {d.get('added_at', '?')}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── /ragclear ─────────────────────────────────────────────────────────────────

async def cmd_ragclear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    count = _agent.rag_clear(user_id)
    await update.message.reply_text(
        f"🗑️ Cleared *{count}* document(s) from your knowledge base.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /search ──────────────────────────────────────────────────────────────────

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.message.reply_text(
            "Usage: `/search <query>`\nContoh: `/search harga emas hari ini`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)
    await update.message.reply_text(f"🔍 Searching: _{query}_…", parse_mode=ParseMode.MARKDOWN)

    user_id = update.effective_user.id
    try:
        reply = await _agent.handle_search(user_id, query)
    except Exception as e:
        logger.error(f"Search failed: {e}")
        await update.message.reply_text(f"Search failed: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    for chunk in _split(reply, 4096):
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN,
                                        disable_web_page_preview=True)


# ── /browse ───────────────────────────────────────────────────────────────────

async def cmd_browse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = " ".join(context.args).strip() if context.args else ""
    if not url:
        await update.message.reply_text(
            "Usage: `/browse <url>`\nContoh: `/browse https://example.com`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    await update.message.chat.send_action(ChatAction.TYPING)
    await update.message.reply_text(f"🌐 Browsing: `{url}`…", parse_mode=ParseMode.MARKDOWN)

    user_id = update.effective_user.id
    try:
        reply = await _agent.handle_browse(user_id, url)
    except Exception as e:
        logger.error(f"Browse failed: {e}")
        await update.message.reply_text(f"Browse failed: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    for chunk in _split(reply, 4096):
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN,
                                        disable_web_page_preview=True)


# ── /generate ───────────────────────────────────────────────────────────────

# ── /editimg ─────────────────────────────────────────────────────────────────

async def cmd_editimg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/editimg — show instructions for AI image editing."""
    await update.message.reply_text(
        "*✏️ AI Image Editor*\n\n"
        "Kirim gambar ke saya dengan *caption* berisi instruksi editing.\n\n"
        "*Contoh instruksi:*\n"
        "• `hapus watermark`\n"
        "• `remove the watermark and logo`\n"
        "• `hilangkan teks di pojok kanan bawah`\n"
        "• `ganti background jadi putih`\n"
        "• `ubah jadi style anime`\n"
        "• `remove all text overlays`\n"
        "• `make the background blurred`\n\n"
        "*Cara pakai:*\n"
        "1\. Tekan ikon 📎 attachment\n"
        "2\. Pilih gambar yang ingin diedit\n"
        "3\. Sebelum kirim, ketik instruksi di kolom *caption*\n"
        "4\. Kirim — bot akan memproses dan mengembalikan hasil edit\n\n"
        "_Catatan: hasil editing menggunakan AI generatif \(Flux\)\. "
        "Gambar di-regenerate berdasarkan deskripsi \+ instruksimu\._",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = " ".join(context.args).strip() if context.args else ""
    if not prompt:
        await update.message.reply_text(
            "Usage: `/generate <description>`\nExample: `/generate a sunset over Tokyo, cyberpunk, photorealistic`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.chat.send_action(ChatAction.UPLOAD_PHOTO)
    await update.message.reply_text(f"🎨 Generating: _{prompt[:100]}_…", parse_mode=ParseMode.MARKDOWN)
    try:
        img_bytes = await generate_image(prompt)
        await update.message.reply_photo(photo=img_bytes, caption=f"🖼 {prompt[:200]}")
    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        await update.message.reply_text(f"Generation failed: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ── Photo handler ─────────────────────────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Photo received:
      • No caption  → analyze and describe.
      • With caption → edit the image based on the caption.
    """
    user_id = update.effective_user.id
    caption = (update.message.caption or "").strip()

    # Download highest-resolution photo
    photo = update.message.photo[-1]
    await update.message.chat.send_action(ChatAction.UPLOAD_PHOTO)
    file = await context.bot.get_file(photo.file_id)
    img_bytes: bytes = await file.download_as_bytearray()

    if not caption:
        # ── Analyze mode ──────────────────────────────────────────────────
        await update.message.reply_text("🔍 Analyzing your image…")
        try:
            description = await analyze_image(img_bytes, "Describe this image in detail.")
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            await update.message.reply_text(f"Analysis failed: `{e}`", parse_mode=ParseMode.MARKDOWN)
            return
        # Store in conversation memory
        _agent._memory.append(user_id, "user", "[User sent an image]")
        _agent._memory.append(user_id, "assistant", f"[Image description]: {description}")
        for chunk in _split(description, 4096):
            await update.message.reply_text(chunk)
    else:
        # ── Edit mode ─────────────────────────────────────────────────────
        await update.message.reply_text(f"✏️ Editing image: _{caption[:100]}_…", parse_mode=ParseMode.MARKDOWN)
        try:
            new_img, desc = await edit_image(img_bytes, caption)
        except Exception as e:
            logger.error(f"Image edit failed: {e}")
            await update.message.reply_text(f"Edit failed: `{e}`", parse_mode=ParseMode.MARKDOWN)
            return
        _agent._memory.append(user_id, "user", f"[User sent image with edit request: {caption}]")
        _agent._memory.append(user_id, "assistant", f"[Edited image generated. Original: {desc}]")
        await update.message.reply_photo(photo=new_img, caption=f"✅ Edited: {caption[:200]}")


# ── Plain messages → chat ─────────────────────────────────────────────────

_SCAN_TRIGGER = re.compile(
    r"""
    (?:
        # "scan ulang/lagi" — rescan last target
        (?P<rescan>scan\s+(?:ulang|lagi|again|recheck|re-?scan)\b)
        |
        # "scan <target>", "cek keamanan <target>", "apakah <target> rentan", "analisis <target>"
        (?:
            (?:scan|cek\s+keamanan|periksa\s+keamanan|analisis\s+keamanan|check\s+security|scan\s+website)\s+
            (?P<target1>[\w.\-:/]+)
        )
        |
        (?:
            (?:apakah|is|whether)\s+(?P<target2>[\w.\-:/]+)\s+(?:rentan|vulnerable|aman|safe)
        )
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text or ""
    if not text.strip():
        return

    # ── Auto-trigger scan from plain-text requests ────────────────────────
    m = _SCAN_TRIGGER.search(text)
    if m:
        if m.group("rescan"):
            # Use last scanned target stored in user_data
            target = (context.user_data or {}).get("last_scan_target", "")
            if not target:
                await update.message.reply_text(
                    "Belum ada target scan sebelumnya. Gunakan /scan <domain>."
                )
                return
        else:
            target = (m.group("target1") or m.group("target2") or "").strip()

        if target:
            context.user_data["last_scan_target"] = target
            await update.message.chat.send_action(ChatAction.TYPING)
            status_msg = await update.message.reply_text(
                f"Scanning {target}...\nChecking ports, SSL, headers, sensitive paths — harap tunggu ±30 detik."
            )
            try:
                report, txt_path = await _agent.handle_scan(user_id, target)
            except Exception as e:
                logger.error(f"Scan failed for {target}: {e}")
                await status_msg.edit_text(f"Scan gagal: {e}")
                return
            await status_msg.delete()
            for chunk in _split(report, 4096):
                await update.message.reply_text(chunk)
            try:
                import os as _os
                if txt_path and _os.path.exists(str(txt_path)):
                    with open(str(txt_path), "rb") as _f:
                        await update.message.reply_document(
                            document=_f,
                            filename=_os.path.basename(str(txt_path)),
                            caption=f"📄 Scan report: {target}",
                        )
            except Exception as _e:
                logger.warning(f"Could not send scan file: {_e}")
            return

    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        reply = await _agent.chat(user_id, text)
    except Exception as e:
        logger.error(f"Chat error for user {user_id}: {e}")
        await update.message.reply_text(f"Error: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    logger.info(f"Reply to {user_id}: {len(reply)} chars")
    # Telegram message limit: 4096 chars
    if len(reply) <= 4096:
        await update.message.reply_text(reply)
    else:
        for chunk in _split(reply, 4096):
            await update.message.reply_text(chunk)


def _split(text: str, size: int) -> list[str]:
    return [text[i: i + size] for i in range(0, len(text), size)]


_SCAN_OUT_DIR = Path("output/scans")


def _save_report(report_text: str, prefix: str, target: str, user_id: int | str) -> Path:
    """Save a plain-text scan report to output/scans/<prefix>/."""
    out_dir = _SCAN_OUT_DIR / prefix
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]", "_", target.replace("https://", "").replace("http://", "").strip("/"))[:60]
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{safe}_{ts}_user{user_id}"
    txt_path = out_dir / f"{stem}.txt"
    txt_path.write_text(report_text, encoding="utf-8")
    return txt_path


# ── /scrape ───────────────────────────────────────────────────────────────────

async def cmd_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /scrape <url>           — fetch & extract data from a URL
    /scrape <url> --save    — fetch + save result as local file
    /scrape <nama orang>    — cari profil + akun sosmed via Wikidata/Wikipedia

    After saving, use /datasearch and /datashow to work with the data locally.
    """
    args = list(context.args) if context.args else []

    if not args:
        await update.message.reply_text(
            "🕷️ *Web Scraper & Pencarian Entitas*\n\n"
            "*Scrape URL:*\n"
            "`/scrape <url>` — ambil data dari halaman web\n"
            "`/scrape <url> --save` — ambil + simpan ke file lokal\n\n"
            "*Cari orang/organisasi:*\n"
            "`/scrape joko widodo` — profil + akun sosmed resmi\n"
            "`/scrape prabowo subianto` — info + Instagram/Facebook/dll\n"
            "`/scrape Bank Indonesia` — info lembaga\n\n"
            "_Tip: /datalist, /datashow, /datasearch untuk akses data tersimpan._",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Parse flags
    save = "--save" in args
    args = [a for a in args if a != "--save"]

    table_idx = 0
    if "--table" in args:
        ti = args.index("--table")
        if ti + 1 < len(args):
            try:
                table_idx = int(args[ti + 1]) - 1
                args.pop(ti + 1)
            except ValueError:
                pass
            args.pop(ti)

    query = " ".join(args).strip()
    if not query:
        await update.message.reply_text("❌ Query tidak diberikan.")
        return

    await update.message.chat.send_action(ChatAction.TYPING)

    # ── Branch: URL scrape vs. entity/person search ────────────────────────
    first_token = args[0] if args else query
    if is_url_or_domain(first_token):
        url = first_token
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        status = await update.message.reply_text(
            f"🕷️ Scraping `{url[:60]}`…",
            parse_mode=ParseMode.MARKDOWN,
        )
        try:
            reply_text, _ = await scrape_and_format(
                url, save=save, table_index=table_idx
            )
        except Exception as e:
            logger.error(f"Scrape failed for {url}: {e}")
            await status.edit_text(f"❌ Scrape gagal: `{e}`", parse_mode=ParseMode.MARKDOWN)
            return
        await status.delete()
        for chunk in _split(reply_text, 4096):
            await update.message.reply_text(
                chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
            )

    else:
        # Entity / person search
        status = await update.message.reply_text(
            f"🔍 Mencari *{query}* di Wikidata…",
            parse_mode=ParseMode.MARKDOWN,
        )
        try:
            reply_text = await search_entity(query)
        except Exception as e:
            logger.error(f"Entity search failed for '{query}': {e}")
            await status.edit_text(f"❌ Pencarian gagal: `{e}`", parse_mode=ParseMode.MARKDOWN)
            return
        await status.delete()
        for chunk in _split(reply_text, 4096):
            await update.message.reply_text(
                chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
            )


# ── /crawl ───────────────────────────────────────────────────────────────────

async def cmd_crawl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /crawl <url>                       — crawl situs, ikuti link internal (depth=5, max=50)
    /crawl <url> --depth 3             — crawl lebih dalam
    /crawl <url> --max 20              — lebih banyak halaman
    /crawl <url> --save                — simpan hasil ke file lokal
    """
    if not update.message:
        return
    args = list(context.args) if context.args else []

    if not args:
        await update.message.reply_text(
            "🕸️ *Web Crawler*\n\n"
            "`/crawl <url>` — crawl situs mulai dari URL ini\n"
            "`/crawl <url> --depth 3` — ikuti link sampai kedalaman 3\n"
            "`/crawl <url> --max 20` — crawl hingga 20 halaman\n"
            "`/crawl <url> --save` — simpan semua hasil + link ke file lokal\n\n"
            "_Hanya mengikuti link internal (domain yang sama)._",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Parse flags
    save = "--save" in args
    args = [a for a in args if a != "--save"]

    depth = 5
    if "--depth" in args:
        di = args.index("--depth")
        if di + 1 < len(args):
            try:
                depth = max(1, min(int(args[di + 1]), 10))
                args.pop(di + 1)
            except ValueError:
                pass
            args.pop(di)

    max_pages = 50
    if "--max" in args:
        mi = args.index("--max")
        if mi + 1 < len(args):
            try:
                max_pages = max(1, min(int(args[mi + 1]), 200))
                args.pop(mi + 1)
            except ValueError:
                pass
            args.pop(mi)

    url = args[0] if args else ""
    if not url:
        await update.message.reply_text("❌ URL tidak diberikan.")
        return

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    status = await update.message.reply_text(
        f"🕸️ Crawling `{url[:60]}`…\n"
        f"_depth={depth}, max={max_pages} halaman_",
        parse_mode=ParseMode.MARKDOWN,
    )
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        reply_text, _ = await crawl_and_format(
            url, max_pages=max_pages, depth=depth, save=save
        )
    except Exception as e:
        logger.error(f"Crawl failed for {url}: {e}")
        await status.edit_text(f"❌ Crawl gagal: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    await status.delete()
    for chunk in _split(reply_text, 4096):
        await update.message.reply_text(
            chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )


# ── /datalist ─────────────────────────────────────────────────────────────────

async def cmd_datalist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all locally saved datasets from /scrape --save."""
    datasets = list_datasets()
    if not datasets:
        await update.message.reply_text(
            "📂 Belum ada dataset lokal.\n\n"
            "Gunakan `/scrape <url> --save` untuk menyimpan data dari web.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = [f"📂 *Dataset Lokal* — {len(datasets)} file\n"]
    for i, d in enumerate(datasets, 1):
        icon = {"csv": "📊", "json": "📋", "txt": "📄"}.get(d["ext"].lstrip("."), "📁")
        lines.append(
            f"{i}. {icon} `{d['name']}`\n"
            f"   {d['size_kb']} KB — {d['modified']}"
        )
    lines.append(
        "\n_Gunakan:_\n"
        "`/datashow <nama_file>` — lihat isi\n"
        "`/datasearch <nama_file> <query>` — cari data"
    )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── /datashow ─────────────────────────────────────────────────────────────────

async def cmd_datashow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /datashow <filename>
    Show first 20 rows of a saved local dataset.
    """
    args = list(context.args) if context.args else []
    if not args:
        await update.message.reply_text(
            "Usage: `/datashow <nama_file>`\n\n"
            "Contoh: `/datashow wikipedia_daftar_menteri_20260512.csv`\n\n"
            "Gunakan /datalist untuk lihat file yang tersedia.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    filename = args[0]
    result = show_dataset(filename)
    for chunk in _split(result, 4096):
        await update.message.reply_text(
            chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )


# ── /datasearch ───────────────────────────────────────────────────────────────

async def cmd_datasearch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /datasearch <filename> <query>
    Search inside a locally saved dataset without hitting the web.
    """
    args = list(context.args) if context.args else []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/datasearch <nama_file> <query>`\n\n"
            "Contoh:\n"
            "`/datasearch menteri_esdm.csv Prabowo`\n"
            "`/datasearch wiki_dpr.csv PKS`\n\n"
            "Gunakan /datalist untuk lihat file yang tersedia.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    filename = args[0]
    query = " ".join(args[1:])

    await update.message.chat.send_action(ChatAction.TYPING)
    result = search_dataset(filename, query)
    for chunk in _split(result, 4096):
        await update.message.reply_text(
            chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )


# ── /dirscan ──────────────────────────────────────────────────────────────

async def cmd_dirscan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /dirscan <url>           — standard wordlist (~150 paths)
    /dirscan <url> --api     — API-focused wordlist (~90 paths)
    /dirscan <url> --deep    — extended wordlist (~300 paths)
    """
    if not update.message:
        return
    args = list(context.args) if context.args else []

    if not args:
        await update.message.reply_text(
            "📂 *Directory Scanner*\n\n"
            "`/dirscan <url>` — cari folder & file tersembunyi (\\~150 paths)\n"
            "`/dirscan <url> --api` — fokus ke API endpoints\n"
            "`/dirscan <url> --deep` — wordlist lebih besar (\\~300 paths)\n\n"
            "_Berguna untuk menemukan /admin, /api, /backup, /config, dll._",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    mode = "standard"
    if "--api" in args:
        mode = "api"
        args = [a for a in args if a != "--api"]
    elif "--deep" in args:
        mode = "deep"
        args = [a for a in args if a != "--deep"]

    target = args[0] if args else ""
    if not target:
        await update.message.reply_text("❌ URL/domain tidak diberikan.")
        return

    mode_label = {"api": "API Mode", "deep": "Deep Mode"}.get(mode, "Standard")
    status = await update.message.reply_text(
        f"📂 DirScan `{target}` ({mode_label})…\n_Mohon tunggu, sedang probe ratusan path._",
        parse_mode=ParseMode.MARKDOWN,
    )
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        report = await dirscan_target(target, mode=mode)
    except Exception as e:
        logger.error(f"Dirscan failed for {target}: {e}")
        await status.edit_text(f"❌ DirScan gagal: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    saved = _save_report(report, "dirscan", target, update.effective_user.id)
    logger.info(f"Dirscan saved: {saved}")

    await status.delete()
    for chunk in _split(report, 4096):
        await update.message.reply_text(chunk, parse_mode=None)


# ── /apiscan ─────────────────────────────────────────────────────────────

async def cmd_apiscan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /apiscan <url>  — detect API types: GraphQL, REST, SOAP, JSON-RPC, gRPC, OData, WebSocket
    """
    if not update.message:
        return
    args = list(context.args) if context.args else []

    if not args:
        await update.message.reply_text(
            "🔌 *API Type Scanner*\n\n"
            "`/apiscan <url>` — deteksi jenis API yang dipakai sebuah website\n\n"
            "*Apa yang dicek:*\n"
            "• 🔮 *GraphQL* — introspection probe, playground UI\n"
            "• 📡 *REST* — Swagger/OpenAPI docs discovery\n"
            "• 🧼 *SOAP* — WSDL endpoint probe\n"
            "• 🔧 *JSON-RPC* — method enumeration probe\n"
            "• ⚡ *gRPC* — content-type & trailer headers\n"
            "• 📊 *OData* — \\$metadata endpoint\n"
            "• 🔄 *WebSocket* — Upgrade handshake probe\n\n"
            "_Contoh: `/apiscan api.example.com`_",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    target = args[0]
    status = await update.message.reply_text(
        f"🔌 API Scan `{target}`…\n_Sedang probe semua jenis API, mohon tunggu._",
        parse_mode=ParseMode.MARKDOWN,
    )
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        report = await api_scan(target)
    except Exception as e:
        logger.error(f"API scan failed for {target}: {e}")
        await status.edit_text(f"❌ API Scan gagal: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    saved = _save_report(report, "apiscan", target, update.effective_user.id)
    logger.info(f"API scan saved: {saved}")

    await status.delete()
    for chunk in _split(report, 4096):
        await update.message.reply_text(chunk, parse_mode=None)


# ── /aiscan ──────────────────────────────────────────────────────────────

async def cmd_cmsscan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /cmsscan <cms> [count] [topic] [negara:XX]
    Discover sites running a specific CMS via Exa, then scan each automatically.
    """
    if not update.message:
        return
    args = list(context.args) if context.args else []
    cms_list_str = ", ".join(CMS_SIGNATURES.keys())

    # Country code → full name map for cleaner Exa queries
    _CC_MAP: dict[str, str] = {
        "id": "Indonesia", "my": "Malaysia", "sg": "Singapore", "th": "Thailand",
        "ph": "Philippines", "vn": "Vietnam", "mm": "Myanmar", "kh": "Cambodia",
        "us": "United States", "uk": "United Kingdom", "gb": "United Kingdom",
        "au": "Australia", "nz": "New Zealand", "ca": "Canada",
        "de": "Germany", "fr": "France", "it": "Italy", "es": "Spain",
        "nl": "Netherlands", "be": "Belgium", "se": "Sweden", "no": "Norway",
        "pl": "Poland", "ru": "Russia", "tr": "Turkey",
        "br": "Brazil", "ar": "Argentina", "mx": "Mexico", "co": "Colombia",
        "cl": "Chile", "pe": "Peru", "ec": "Ecuador",
        "in": "India", "pk": "Pakistan", "bd": "Bangladesh", "lk": "Sri Lanka",
        "cn": "China", "jp": "Japan", "kr": "South Korea", "tw": "Taiwan",
        "hk": "Hong Kong",
        "za": "South Africa", "ng": "Nigeria", "ke": "Kenya", "eg": "Egypt",
        "ae": "United Arab Emirates", "sa": "Saudi Arabia", "il": "Israel",
    }

    if not args:
        await update.message.reply_text(
            "\U0001f3ea CMS AutoScan\n\n"
            "Cari website dengan CMS tertentu via Exa, lalu scan satu per satu secara otomatis.\n\n"
            "Usage: /cmsscan <cms> [jumlah] [topik] [negara:XX]\n"
            f"CMS tersedia: {cms_list_str}\n\n"
            "Contoh:\n"
            "  /cmsscan joomla 5\n"
            "  /cmsscan shopify 5 shoes\n"
            "  /cmsscan magento 10 electronics negara:id\n"
            "  /cmsscan wordpress 5 fashion negara:brazil\n"
            "  /cmsscan prestashop 5 negara:fr\n\n"
            "Kode negara: id=Indonesia, my=Malaysia, us=USA, br=Brazil, de=Germany, dsb.\n"
            "Output disimpan ke output/scans/cms_autoscan/",
            parse_mode=None,
        )
        return

    cms_name = args[0]
    try:
        max_sites = int(args[1]) if len(args) > 1 else 5
        max_sites = max(1, min(max_sites, 15))   # clamp 1-15
    except ValueError:
        max_sites = 5

    # Parse country flag: negara:XX / country:XX / cc:XX from any arg position
    country = ""
    remaining: list[str] = []
    for a in args[2:]:
        lo = a.lower()
        matched = False
        for prefix in ("negara:", "country:", "cc:"):
            if lo.startswith(prefix):
                raw_cc = a[len(prefix):].strip()
                country = _CC_MAP.get(raw_cc.lower(), raw_cc.capitalize())
                matched = True
                break
        if not matched:
            remaining.append(a)

    # Remaining args after count and country flag = topic
    topic = " ".join(remaining)

    # Validate CMS name early
    cms_key = next((k for k in CMS_SIGNATURES if k.lower() == cms_name.lower()), None)
    if not cms_key:
        await update.message.reply_text(
            f"CMS tidak dikenal: '{cms_name}'\n"
            f"Pilihan: {cms_list_str}",
            parse_mode=None,
        )
        return

    _label = cms_key
    if topic:
        _label += f" [{topic}]"
    if country:
        _label += f" @{country}"
    status_msg = await update.message.reply_text(
        f"\U0001f3ea CMS AutoScan: {_label}\n"
        f"Mencari {max_sites} target via Exa...\n"
        "(Mohon tunggu, proses berjalan)",
        parse_mode=None,
    )
    await update.message.chat.send_action(ChatAction.TYPING)

    progress_lines: list[str] = []

    async def on_progress(msg: str) -> None:
        progress_lines.append(msg)
        try:
            preview = "\n".join(progress_lines[-10:])
            await status_msg.edit_text(
                f"\U0001f3ea CMS AutoScan: {_label}\n\n{preview}",
                parse_mode=None,
            )
        except Exception:
            pass

    try:
        result = await auto_scan_cms(
            cms_name,
            max_sites=max_sites,
            progress_cb=on_progress,
            topic=topic,
            country=country,
        )
    except Exception as e:
        logger.error(f"cmsscan error: {e}")
        await status_msg.edit_text(f"Gagal: {e}", parse_mode=None)
        return

    if result.get("error") and not result.get("scan_results"):
        await status_msg.edit_text(
            f"CMS AutoScan: {cms_key}\nGagal: {result['error']}",
            parse_mode=None,
        )
        return

    # Build final summary
    domains      = result.get("domains", [])
    scan_results = result.get("scan_results", [])
    lines = [
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        f"\U0001f3ea CMS AUTOSCAN SELESAI",
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
        f"CMS     : {result['cms']}",
        f"Ditemukan: {len(domains)} domain",
        f"Di-scan : {len(scan_results)} target",
        f"Domain  : {result.get('domains_file','')}",
        f"Summary : {result.get('summary_file','')}",
        "",
    ]

    risk_emoji = {"KRITIS": "\U0001f534", "TINGGI": "\U0001f7e0", "SEDANG": "\U0001f7e1", "RENDAH": "\U0001f7e2"}
    for r in scan_results:
        info   = r.get("info", {})
        counts = r.get("counts", {})
        risk   = r.get("risk_level", "?")
        src    = r.get("_source_domain", info.get("target", "?"))
        if r.get("error") and not r.get("findings"):
            lines.append(f"\u274c {src}: {r['error']}")
        else:
            em = risk_emoji.get(risk, "\u26aa")
            lines.append(f"{em} {src}")
            lines.append(
                f"   Risk: {risk} | "
                f"\U0001f534{counts.get('CRITICAL',0)} "
                f"\U0001f7e0{counts.get('HIGH',0)} "
                f"\U0001f7e1{counts.get('MEDIUM',0)} "
                f"\U0001f535{counts.get('LOW',0)}"
            )
            if r.get("waf"):
                lines.append(f"   WAF: {r['waf']}")
            detected = info.get("detected_cms", [])
            if detected:
                lines.append(f"   CMS: {', '.join(detected)}")
            fp = info.get("found_paths", [])
            if fp:
                lines.append(f"   Paths: {', '.join(fp[:6])}")
        lines.append("")

    await status_msg.delete()
    for chunk in _split("\n".join(lines), 4096):
        await update.message.reply_text(chunk, parse_mode=None)

    # ── Send files as Telegram documents ──────────────────────────────────
    import os as _os
    # 1. Summary .txt (overview of all sites)
    summary_file = result.get("summary_file", "")
    if summary_file and _os.path.exists(summary_file):
        try:
            with open(summary_file, "rb") as _f:
                await update.message.reply_document(
                    document=_f,
                    filename=_os.path.basename(summary_file),
                    caption=f"📋 Summary: {cms_key}" + (f" [{topic}]" if topic else "") + (f" @{country}" if country else ""),
                )
        except Exception as _e:
            logger.warning(f"Could not send summary file: {_e}")

    # 2. Individual scan JSONs (one per site)
    for r in result.get("scan_results", []):
        json_path = r.get("_json_path", "")
        if not json_path or not _os.path.exists(str(json_path)):
            continue
        src = r.get("_source_domain", r.get("info", {}).get("target", ""))
        risk = r.get("risk_level", "?")
        counts = r.get("counts", {})
        caption = (
            f"🔍 {src}\n"
            f"Risk: {risk} | "
            f"🔴{counts.get('CRITICAL',0)} "
            f"🟠{counts.get('HIGH',0)} "
            f"🟡{counts.get('MEDIUM',0)} "
            f"🔵{counts.get('LOW',0)}"
        )
        if r.get("waf"):
            caption += f"\nWAF: {r['waf']}"
        try:
            with open(str(json_path), "rb") as _f:
                await update.message.reply_document(
                    document=_f,
                    filename=_os.path.basename(str(json_path)),
                    caption=caption,
                )
        except Exception as _e:
            logger.warning(f"Could not send scan JSON {json_path}: {_e}")


async def cmd_aiscan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /aiscan <url>  — AI-guided iterative security scan.
    Round 1: Fingerprint + LLM generates targeted paths → probe
    Round 2: Feed findings → LLM generates deeper paths → probe again
    """
    if not update.message:
        return
    args = list(context.args) if context.args else []
    if not args:
        await update.message.reply_text(
            "🤖 *AI-Guided Security Scanner*\n\n"
            "`/aiscan <url>` — scan iteratif dengan AI sebagai guide\n\n"
            "*Cara kerja:*\n"
            "1. Fingerprint target (tech stack, server, WAF)\n"
            "2. AI generate probe paths berdasarkan fingerprint\n"
            "3. Execute probes → kumpulkan hasil\n"
            "4. AI generate probe lanjutan berdasarkan temuan\n"
            "5. Execute round 2 → laporan final\n\n"
            "_Contoh: `/aiscan example.com`_",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    target = args[0]
    status = await update.message.reply_text(
        f"🤖 AI Scan `{target}`…\n"
        "_Fingerprinting → AI generating probes → scanning…_\n"
        "_(Mohon tunggu, 2 round AI-guided probing)_",
        parse_mode=ParseMode.MARKDOWN,
    )
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        report = await aiscan_target(target)
    except Exception as e:
        logger.error(f"AI scan failed for {target}: {e}")
        await status.edit_text(f"❌ AI Scan gagal: `{e}`", parse_mode=ParseMode.MARKDOWN)
        return

    saved = _save_report(report, "aiscan", target, update.effective_user.id)
    logger.info(f"AI scan saved: {saved}")

    await status.delete()
    for chunk in _split(report, 4096):
        await update.message.reply_text(chunk, parse_mode=None)


# ── Error handler ─────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler. On Conflict, exit immediately — another instance is running."""
    if isinstance(context.error, Conflict):
        logger.critical(
            "telegram.error.Conflict — another bot instance is already polling. "
            "Kill all other Python/bot processes and restart. Exiting now."
        )
        # Clean up lock file BEFORE os._exit so next start isn't blocked
        _LOCK_FILE = os.path.join(os.path.dirname(__file__), "..", ".hermes.lock")
        try:
            os.remove(os.path.normpath(_LOCK_FILE))
        except OSError:
            pass
        os._exit(1)
    logger.error("Unhandled exception:", exc_info=context.error)


# ── Application factory ───────────────────────────────────────────────────

def build_application(token: str) -> Application:
    import config as _cfg
    from telegram.request import HTTPXRequest

    request = HTTPXRequest(
        connect_timeout=_cfg.TELEGRAM_CONNECT_TIMEOUT,
        read_timeout=_cfg.TELEGRAM_READ_TIMEOUT,
        **(dict(proxy=_cfg.TELEGRAM_PROXY) if _cfg.TELEGRAM_PROXY else {}),
    )
    app = Application.builder().token(token).request(request).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("sessions", cmd_sessions))
    app.add_handler(CommandHandler("newsession", cmd_newsession))
    app.add_handler(CommandHandler("switch", cmd_switch))
    app.add_handler(CommandHandler("rename", cmd_rename))
    app.add_handler(CommandHandler("delsession", cmd_delsession))
    app.add_handler(CommandHandler("ppt", cmd_ppt))
    app.add_handler(CommandHandler("analys", cmd_analys))
    app.add_handler(CommandHandler("parafrase", cmd_parafrase))
    app.add_handler(CommandHandler("gptzero", cmd_gptzero))
    app.add_handler(CommandHandler("datastats", cmd_datastats))
    app.add_handler(CommandHandler("upload", cmd_upload))
    app.add_handler(CommandHandler("raglist", cmd_raglist))
    app.add_handler(CommandHandler("ragclear", cmd_ragclear))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("browse", cmd_browse))
    app.add_handler(CommandHandler("dns", cmd_dns))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("bulkscan", cmd_bulkscan))
    app.add_handler(CommandHandler("dirscan", cmd_dirscan))
    app.add_handler(CommandHandler("apiscan", cmd_apiscan))
    app.add_handler(CommandHandler("aiscan",   cmd_aiscan))
    app.add_handler(CommandHandler("cmsscan",  cmd_cmsscan))
    app.add_handler(CommandHandler("editimg", cmd_editimg))
    app.add_handler(CommandHandler("generate", cmd_generate))
    app.add_handler(CommandHandler("video", cmd_video))
    app.add_handler(CommandHandler("scrape", cmd_scrape))
    app.add_handler(CommandHandler("crawl", cmd_crawl))
    app.add_handler(CommandHandler("datalist", cmd_datalist))
    app.add_handler(CommandHandler("datasearch", cmd_datasearch))
    app.add_handler(CommandHandler("datashow", cmd_datashow))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.add_error_handler(error_handler)

    return app