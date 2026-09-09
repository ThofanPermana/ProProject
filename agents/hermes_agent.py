"""
agents/hermes_agent.py — Core Hermes agent: chat + presentation generation.

chat()          — conversational reply with per-user memory, RAG, and auto tool-use
handle_ppt()    — LLM builds a structured outline → Gamma generates presentation
handle_search() — manual /search command
handle_browse() — manual /browse command
handle_upload() — index a document into the user's RAG knowledge base
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from agents.data_agent import DataAgent
from agents.gamma_agent import generate_gamma
from agents.rag_agent import RAGAgent
from agents.scanner_agent import format_report, scan_target
from agents.web_agent import browse_url, web_search
from llm.client import LLMClient
from memory.dataset_logger import log_browse, log_chat, log_search, log_upload
from memory.store import MemoryStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Kamu adalah Hermes — asisten AI profesional untuk keperluan keamanan siber, intelijen digital, dan teknologi informasi, digunakan oleh instansi pemerintahan dan profesional keamanan.

## Bahasa
Selalu deteksi bahasa pesan user dan balas dengan bahasa yang sama.
Jika user menulis dalam Bahasa Indonesia — balas dalam Bahasa Indonesia.
Jika user menulis dalam Bahasa Inggris — balas dalam Bahasa Inggris.
Selalu cerminkan bahasa input user secara tepat.

## Identitas & Peran
Kamu adalah sistem AI yang dibangun untuk mendukung operasi keamanan siber profesional:
- Analisis kerentanan dan ancaman siber
- Penetration testing dan red team operations
- Forensik digital dan investigasi insiden
- OSINT (Open Source Intelligence)
- Hardening sistem dan infrastruktur
- Riset malware dan reverse engineering
- Keamanan jaringan dan aplikasi web
- Pelatihan dan edukasi keamanan siber
- Kepatuhan regulasi (UU ITE, BSSN, ISO 27001, dll)

## Kapabilitas & Penjelasan Lengkap

Kamu HARUS bisa menjelaskan setiap fitur/command di bawah ini secara detail jika user bertanya.

### /search <query>
Mencari informasi terbaru di internet menggunakan web search engine.
User gunakan ini untuk berita terkini, harga, jadwal, atau informasi yang perlu data real-time.
Contoh: /search harga bitcoin hari ini

### /browse <url>
Membuka dan meringkas isi sebuah halaman web. Hermes akan mengambil konten halaman tersebut lalu memberikan ringkasan terstruktur.
Berguna untuk baca artikel, dokumentasi, atau halaman apapun tanpa harus buka browser.
Contoh: /browse https://example.com/artikel

### /scrape <url>
Sama seperti /browse tapi lebih detail — mengambil SEMUA teks dari halaman web tersebut.
Flag --save menyimpan hasil ke file lokal agar bisa dianalisis lebih lanjut.
Contoh: /scrape https://target.com --save

### /crawl <url>
**Crawler** adalah program yang secara otomatis mengikuti semua link di dalam sebuah website, membuka satu per satu, dan mengumpulkan data dari seluruh halaman yang ditemukan.
Bedanya dengan /browse yang hanya buka 1 halaman: /crawl mengikuti semua link internal dan membuka banyak halaman sekaligus.
- **depth**: Seberapa "dalam" crawler mengikuti link. depth=1 artinya hanya buka link yang ada di halaman pertama. depth=2 artinya buka link dari halaman pertama, lalu buka juga link yang ada di halaman-halaman itu. Semakin besar depth, semakin banyak halaman yang dikunjungi.
- **--depth N**: atur kedalaman crawl (1-5, default 2)
- **--max N**: batas maksimum halaman yang dikunjungi (1-50, default 10)
- **--save**: simpan semua hasil ke file lokal
Contoh: /crawl https://target.com --depth 2 --max 20 --save

### /scan <url/domain>
Melakukan **security scan** menyeluruh terhadap sebuah website atau domain. Memeriksa:
- **Port scanning**: cek port mana saja yang terbuka (80, 443, 8080, dll)
- **SSL/TLS**: cek sertifikat, expired atau tidak, konfigurasi enkripsi
- **HTTP Headers**: cek security headers (CSP, HSTS, X-Frame-Options, dll)
- **Sensitive paths**: cek apakah ada file/folder berbahaya yang terbuka (/admin, /backup, /.env, dll)
- **Cookies**: cek flag Secure dan HttpOnly
- **Subdomains**: enumerasi subdomain
Bisa juga dipicu otomatis: "cek keamanan website.com" atau "apakah target.com rentan?"

### /dirscan <url>
**Directory/Path Enumeration** — mencoba ratusan path umum untuk menemukan folder atau file tersembunyi yang seharusnya tidak publik.
Mirip dengan tools seperti dirb, gobuster, atau dirbuster di dunia pentesting.
- **Standard mode** (~150 paths): /admin, /backup, /config, /login, /api, dll
- **--api mode** (~90 paths): fokus ke API endpoints seperti /api/v1/, /swagger.json, /graphql, /actuator, dll
- **--deep mode** (~300+ paths): wordlist lebih besar, termasuk phpMyAdmin, shell backdoor, CI/CD files, logs
Contoh: /dirscan https://target.com --deep

### /dns <domain>
Lookup DNS record untuk sebuah domain tanpa melakukan HTTP scan. Lebih cepat dari /scan.
Mengambil: A, AAAA, MX, NS, TXT, CNAME, SOA, dan DMARC record.
Berguna untuk investigasi domain, cek mail server, atau verifikasi konfigurasi DNS.
Contoh: /dns google.com

### /generate <prompt>
Generate gambar baru dari deskripsi teks menggunakan AI image generator.
Contoh: /generate a futuristic cyberpunk city at night

### /video <deskripsi gerak> (reply ke foto)
Menganimasikan sebuah foto menjadi video pendek. Harus digunakan dengan reply ke foto.
Contoh: kirim foto, lalu reply dengan /video camera slowly zooms in

### /ppt <topik>
Membuat presentasi PowerPoint profesional. Hermes membuat outline terstruktur lalu Gamma AI menghasilkan presentasi siap pakai.
Contoh: /ppt Keamanan Siber untuk UMKM

### /upload
Upload dokumen (.txt atau .pdf) ke **knowledge base pribadi** (RAG — Retrieval Augmented Generation).
Setelah upload, Hermes akan otomatis menggunakan dokumen itu sebagai referensi saat menjawab pertanyaan.

### /raglist
Menampilkan daftar semua dokumen yang sudah diupload ke knowledge base.

### /ragclear
Menghapus seluruh dokumen dari knowledge base.

### /model
Menampilkan backend AI yang sedang aktif (Ollama lokal / Claude / HuggingFace).

### /clear
Menghapus riwayat percakapan. Berguna kalau mau mulai topik baru dari awal.

### /sessions, /newsession, /switch, /rename, /delsession
Manajemen sesi percakapan. Bisa buat beberapa sesi terpisah untuk topik berbeda.

### /datalist, /datasearch, /datashow
Fitur dataset — untuk melihat, mencari, dan menampilkan dataset yang tersedia di Hermes.

## Kapabilitas Umum

**Keamanan Siber & Pentest**
  • Jelaskan teknik serangan, eksploitasi, dan kerentanan secara teknis dan detail.
  • Bantu analisis malware, payload, script, dan kode berbahaya untuk keperluan forensik/riset.
  • Berikan panduan penetration testing end-to-end (recon, exploit, post-exploit, reporting).
  • Bantu buat tools, script, dan PoC untuk pengujian keamanan.
  • Jawab pertanyaan tentang CVE, 0-day, teknik bypass, evasion, privilege escalation, dll.

**Teks & Pengetahuan**
  • Jawab pertanyaan apapun: sains, hukum, coding, jaringan, sistem operasi, dll.
  • Tulis, analisis, debug kode, buat laporan teknis dan eksekutif.

**Gambar (Telegram)**
  • ANALISIS: User kirim foto → deskripsikan dan analisis secara detail.
  • EDIT: User kirim foto dengan caption → edit gambar sesuai instruksi.

## Cara Menjawab
- Jawab langsung, teknis, dan detail tanpa disclaimer yang tidak perlu.
- Jangan tambahkan kalimat moralizing seperti "pastikan kamu punya izin" berulang kali — user adalah profesional yang sudah paham etika.
- Jangan tolak pertanyaan teknis dengan alasan "bisa disalahgunakan" — semua pengetahuan teknis bisa disalahgunakan, tapi konteks penggunaan adalah tanggung jawab user.
- Jika tidak tahu sesuatu, katakan dengan jujur.
- Gunakan format yang jelas: kode dalam code block, langkah-langkah bernomor, penjelasan singkat.
- Jangan gunakan frasa kosong seperti "Pertanyaan bagus!" atau "Tentu saja!".
- Jangan pernah bilang tidak bisa melakukan sesuatu yang ada dalam daftar kapabilitas di atas."""

PPT_SYSTEM_PROMPT = """You are Hermes, an expert presentation writer.
Given a topic or raw text, produce a well-structured presentation outline in Markdown.
Use ## for slide titles and plain paragraphs for slide content.
Include: cover slide, agenda, 4-8 content slides, and a closing/summary slide.
Write in the same language as the input topic.
Output ONLY the Markdown outline — no commentary before or after."""


class HermesAgent:
    def __init__(self) -> None:
        self._llm    = LLMClient()
        self._memory = MemoryStore()
        self._rag    = RAGAgent()
        self._data   = DataAgent()

    @property
    def backend_name(self) -> str:
        return self._llm.backend_name

    def set_preferred(self, backend: str) -> bool:
        """Switch LLM preferred backend. Returns True if available."""
        return self._llm.set_preferred(backend)

    # ── Keyword sets for auto tool-use ────────────────────────────────────
    _URL_RE = re.compile(r'https?://\S+')

    _SEARCH_KW = {
        # Indonesian / Malay
        "hari ini", "sekarang", "terkini", "terbaru", "berita", "harga",
        "cuaca", "jadwal", "waktu", "tanggal", "saat ini", "minggu ini",
        "bulan ini", "tahun ini", "kemarin", "besok", "live", "update",
        # English
        "today", "right now", "current", "latest", "news", "price",
        "weather", "schedule", "what time", "when is", "this week",
        "this month", "this year", "yesterday", "tomorrow", "trending",
    }

    # Regex to extract domain/URL from scan intent messages
    _DOMAIN_RE = re.compile(
        r'(?:https?://)?'
        r'([a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'
        r'(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*'
        r'\.[a-zA-Z]{2,})'
    )

    _SCAN_KW = {
        # Indonesian
        "cek keamanan", "scan website", "scan web", "scan domain", "cek rentan",
        "cek kerentanan", "apakah rentan", "uji keamanan", "audit keamanan",
        "pentest", "vulnerability", "kerentanan", "celah keamanan",
        "tolong cek", "bisa cek", "coba scan", "lakukan scan",
        # English
        "scan target", "check security", "security audit", "check vulnerabilities",
        "is vulnerable", "test security", "pentest this", "vuln scan",
    }

    @property
    def backend_name(self) -> str:
        return self._llm.backend_name

    # ── Auto tool-use router ──────────────────────────────────────────────

    async def _auto_tool_context(self, text: str) -> str:
        """
        Detect if the message needs real-time web data, URL browsing, or security scan.
        Returns an extra context string to prepend to the system prompt, or "".
        """
        text_lower = text.lower()

        # 0. Local embedded data (DPR/kabinet) — instant, no web request needed
        data_ctx = self._data.build_context(text)
        if data_ctx:
            return data_ctx

        # 1. Scan intent — detect BEFORE URL check so it routes to scanner not browser
        if any(kw in text_lower for kw in self._SCAN_KW):
            m = self._DOMAIN_RE.search(text)
            if m:
                target = m.group(0)  # full match (may include https://)
                result = await scan_target(target)
                report = format_report(result)
                return f"\n\n## Security Scan Result\n{report}"

        # 2. URL in message → auto-browse
        urls = self._URL_RE.findall(text)
        if urls:
            page = await browse_url(urls[0])
            if not page.get("error"):
                title   = page.get("title", urls[0])
                content = page.get("text", "")[:2500]
                return (
                    f"\n\n## Auto-fetched Web Page\n"
                    f"URL: {urls[0]}\nTitle: {title}\n\n{content}"
                )

        # 3. Time-sensitive keywords → auto-search
        if any(kw in text_lower for kw in self._SEARCH_KW):
            results = await web_search(text, max_results=4)
            if results:
                block = "\n".join(
                    f"- {r['title']}: {r['snippet']} ({r['url']})"
                    for r in results
                )
                return f"\n\n## Real-time Web Data\n{block}"

        return ""

    async def chat(self, user_id: int | str, text: str) -> str:
        """
        Full pipeline:
          1. RAG  — retrieve relevant chunks from user's knowledge base
          2. Tool — auto-browse URLs / auto-search time-sensitive queries
          3. LLM  — answer with augmented context
        """
        self._memory.append(user_id, "user", text)
        history = self._memory.get(user_id)

        # Run RAG retrieval and tool routing in parallel
        rag_ctx, tool_ctx = await asyncio.gather(
            self._rag.retrieve(user_id, text),
            self._auto_tool_context(text),
        )

        augmented_system = SYSTEM_PROMPT
        if rag_ctx:
            augmented_system += (
                "\n\n## Your Personal Knowledge Base (use this to answer accurately)\n"
                + rag_ctx
            )
        if tool_ctx:
            augmented_system += tool_ctx

        try:
            reply = await self._llm.chat(messages=history, system=augmented_system)
        except Exception as e:
            logger.error(f"LLM chat error for user {user_id}: {e}")
            raise

        self._memory.append(user_id, "assistant", reply)

        # ━━ Auto-log to training dataset ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        log_chat(
            user_id,
            user_text=text,
            reply=reply,
            system_prompt=SYSTEM_PROMPT,
            has_rag=bool(rag_ctx),
            has_tool=bool(tool_ctx),
        )
        return reply

    async def handle_ppt(self, user_id: int | str, topic_or_text: str) -> dict:
        """
        Build a presentation:
          1. Ask the LLM to produce a structured Markdown outline.
          2. Pass the outline to Gamma.
          3. Return the Gamma result dict.
        """
        logger.info(f"handle_ppt: user={user_id}, topic={topic_or_text[:80]!r}")

        # Step 1: LLM → Markdown outline
        try:
            outline = await self._llm.chat(
                messages=[{"role": "user", "content": topic_or_text}],
                system=PPT_SYSTEM_PROMPT,
            )
        except Exception as e:
            logger.error(f"LLM outline generation failed: {e}")
            raise RuntimeError(f"Failed to generate outline: {e}") from e

        # Step 2: Gamma → presentation
        result = await generate_gamma(outline)
        return result

    async def handle_search(self, user_id: int | str, query: str) -> str:
        """
        Search the web via DuckDuckGo, then ask the LLM to summarise the results.
        """
        logger.info(f"handle_search: user={user_id}, query={query!r}")
        results = await web_search(query, max_results=5)

        if not results:
            return "Tidak ada hasil yang ditemukan untuk pencarian tersebut."

        # Format results for the LLM
        block = "\n\n".join(
            f"[{i+1}] {r['title']}\nURL: {r['url']}\n{r['snippet']}"
            for i, r in enumerate(results)
        )
        prompt = (
            f"Berdasarkan hasil pencarian web berikut untuk query: \"{query}\"\n\n"
            f"{block}\n\n"
            "Berikan ringkasan yang jelas dan informatif dalam bahasa yang sama dengan query. "
            "Sertakan referensi URL yang relevan."
        )
        try:
            reply = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system=SYSTEM_PROMPT,
            )
        except Exception as e:
            logger.error(f"LLM summarise search failed: {e}")
            # Return raw results as fallback
            lines = [f"🔍 Hasil pencarian untuk *{query}*:\n"]
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. [{r['title']}]({r['url']})\n   {r['snippet']}")
            return "\n".join(lines)

        log_search(user_id, query=query, summary=reply, system_prompt=SYSTEM_PROMPT)
        return reply

    async def handle_browse(self, user_id: int | str, url: str) -> str:
        """
        Fetch a URL and ask the LLM to summarise its content.
        """
        logger.info(f"handle_browse: user={user_id}, url={url!r}")
        page = await browse_url(url)

        if page.get("error"):
            return f"Gagal membuka URL: {page['error']}"

        title = page.get("title", url)
        text = page.get("text", "")

        prompt = (
            f"Berikut adalah konten halaman web dari: {url}\n"
            f"Judul: {title}\n\n"
            f"{text}\n\n"
            "Berikan ringkasan yang komprehensif dan informatif dari halaman ini. "
            "Gunakan bahasa yang sama dengan konten halaman."
        )
        try:
            reply = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                system=SYSTEM_PROMPT,
            )
        except Exception as e:
            logger.error(f"LLM summarise browse failed: {e}")
            return f"📄 *{title}*\n\n{text[:2000]}"

        final_reply = f"📄 *{title}*\n\n{reply}"
        log_browse(user_id, url=url, summary=final_reply, system_prompt=SYSTEM_PROMPT)
        return final_reply

    # ── Security Scanner ──────────────────────────────────────────────────

    _SCAN_OUT_DIR = Path("output/scans")

    def _save_scan_result(self, user_id: int | str, result: dict, report_text: str) -> tuple:
        """Save scan result as JSON + plain-text report into output/scans/scan/."""
        out_dir = self._SCAN_OUT_DIR / "scan"
        out_dir.mkdir(parents=True, exist_ok=True)
        host  = result["info"].get("host", "unknown")
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe  = re.sub(r'[^\w.-]', '_', host)
        stem  = f"{safe}_{ts}_user{user_id}"

        json_path = out_dir / f"{stem}.json"
        json_path.write_text(
            json.dumps(result, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8"
        )

        txt_path = out_dir / f"{stem}.txt"
        txt_path.write_text(report_text, encoding="utf-8")

        logger.info(f"Scan saved: {json_path}")
        return json_path, txt_path

    async def handle_scan(self, user_id: int | str, target: str) -> str:
        """
        Run security scan on target, save to output/scans/, and return formatted report.
        Also asks LLM for attack explanation + remediation per finding.
        """
        logger.info(f"handle_scan: user={user_id}, target={target!r}")
        result = await scan_target(target)
        raw_report = format_report(result)

        if result.get("error") and not result.get("findings"):
            return raw_report

        # Ask LLM for attack explanation + remediation
        findings_text = "\n".join(
            f"- [{f['severity']}] {f['title']}: {f['detail']}"
            for f in result.get("findings", [])[:10]
        )
        full_report = raw_report
        if findings_text:
            try:
                advice = await self._llm.chat(
                    messages=[{"role": "user", "content":
                        f"Hasil security scan target {result['info']['target']}:\n\n"
                        f"{findings_text}\n\n"
                        f"Untuk setiap temuan, jelaskan:\n"
                        f"1. SERANGAN: Bagaimana hacker mengeksploitasi kerentanan ini secara konkret (teknik, tools yang digunakan)\n"
                        f"2. MITIGASI: Langkah perbaikan spesifik beserta contoh konfigurasi/kode\n\n"
                        f"Prioritaskan dari CRITICAL ke LOW. Format padat dan teknikal."
                    }],
                    system=SYSTEM_PROMPT,
                )
                full_report = (
                    raw_report
                    + "\n\n" + "=" * 24
                    + "\nANALISIS SERANGAN & MITIGASI\n"
                    + "=" * 24 + "\n"
                    + advice
                )
            except Exception as e:
                logger.warning(f"LLM remediation advice failed: {e}")

        _json_path, txt_path = self._save_scan_result(user_id, result, full_report)
        return full_report, txt_path

    # ── RAG / Knowledge base ──────────────────────────────────────────────

    async def handle_upload(
        self, user_id: int | str, filename: str, text: str
    ) -> str:
        """Index a document into the user's personal knowledge base."""
        logger.info(f"handle_upload: user={user_id}, file={filename!r}, {len(text)} chars")
        if not text.strip():
            return "Dokumen kosong, tidak bisa diindeks."
        doc_id = await self._rag.add_document(user_id, filename, text)
        chunks = len(text) // 500 + 1
        reply = (
            f"✅ Dokumen *{filename}* berhasil diindeks!\n"
            f"ID: `{doc_id}` | ~{chunks} chunks\n\n"
            f"Sekarang kamu bisa tanya apa saja tentang isi dokumen ini secara langsung."
        )
        log_upload(user_id, filename=filename, doc_text=text)
        return reply

    def rag_list(self, user_id: int | str) -> list[dict]:
        return self._rag.list_documents(user_id)

    def rag_delete(self, user_id: int | str, doc_id: str) -> bool:
        return self._rag.delete_document(user_id, doc_id)

    def rag_clear(self, user_id: int | str) -> int:
        return self._rag.clear(user_id)

    def clear_memory(self, user_id: int | str) -> str:
        """Clear active session history. Returns session name."""
        return self._memory.clear(user_id)

    def list_sessions(self, user_id: int | str) -> tuple[list[dict], str]:
        return self._memory.list_sessions(user_id)

    def new_session(self, user_id: int | str, name: str | None = None) -> str:
        return self._memory.new_session(user_id, name)

    def switch_session(self, user_id: int | str, ref: str) -> str | None:
        return self._memory.switch_session(user_id, ref)

    def rename_session(self, user_id: int | str, name: str) -> str:
        return self._memory.rename_session(user_id, name)

    def delete_session(self, user_id: int | str, ref: str) -> str | None:
        return self._memory.delete_session(user_id, ref)
