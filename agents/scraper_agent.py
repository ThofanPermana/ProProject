"""
agents/scraper_agent.py — General-purpose web scraper for Hermes.

Capabilities:
  • Fetch any URL and extract: text, tables, lists, structured data
  • Auto-detect content type (HTML table, wiki table, JSON, plain text)
  • Save results as CSV or JSON in outputs/scraped/
  • Search/query saved local datasets without hitting the web again
  • Works great with Wikipedia, government sites, data portals

Commands via Telegram:
  /scrape <url>              — fetch & extract data from URL
  /scrape <url> --save       — fetch + save to local file
  /datalist                  — list saved local datasets
  /datasearch <file> <query> — search inside a saved dataset
  /datashow <file>           — show first 20 rows of a saved dataset
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── Output directory for saved scraped data ────────────────────────────────
_BASE_DIR = Path(__file__).parent.parent / "outputs" / "scraped"
_BASE_DIR.mkdir(parents=True, exist_ok=True)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Wikimedia/Wikidata requires a descriptive non-browser User-Agent
_WIKI_HEADERS = {
    "User-Agent": "HermesAIBot/1.0 (https://github.com/hermes-ai; contact@hermes-ai.local)",
    "Accept": "application/json",
    "Accept-Language": "id,en",
}
_TIMEOUT = 20.0


# ── Helpers ────────────────────────────────────────────────────────────────

def _safe_filename(url: str) -> str:
    """Generate a safe filename from a URL."""
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "").replace(".", "_")
    path = re.sub(r"[^\w]", "_", parsed.path.strip("/"))[:40]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{host}_{path}_{ts}" if path else f"{host}_{ts}"


def _clean_cell(s: str) -> str:
    """Clean a table cell: strip whitespace, collapse newlines."""
    s = re.sub(r"\s+", " ", s.strip())
    return s


def _extract_tables(soup: BeautifulSoup) -> list[dict]:
    """Extract all HTML tables as list of dicts with headers."""
    tables_out = []
    for i, table in enumerate(soup.find_all("table"), 1):
        headers: list[str] = []
        rows: list[dict] = []

        # Try to find header row
        header_row = table.find("tr")
        if header_row:
            ths = header_row.find_all(["th", "td"])
            headers = [_clean_cell(th.get_text()) for th in ths]
            if not any(headers):
                headers = []

        # Process all rows
        all_rows = table.find_all("tr")
        start = 1 if headers else 0
        for tr in all_rows[start:]:
            cells = [_clean_cell(td.get_text()) for td in tr.find_all(["td", "th"])]
            if not any(cells):
                continue
            if headers and len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))
            elif headers and cells:
                # Pad or trim
                row = {}
                for j, h in enumerate(headers):
                    row[h] = cells[j] if j < len(cells) else ""
                rows.append(row)
            elif cells:
                rows.append({f"col_{j}": c for j, c in enumerate(cells)})

        if rows:
            tables_out.append({
                "table_index": i,
                "headers":     headers,
                "row_count":   len(rows),
                "rows":        rows,
            })

    return tables_out


def _extract_lists(soup: BeautifulSoup) -> list[str]:
    """Extract all <ul>/<ol> list items as plain text."""
    items = []
    for li in soup.find_all("li"):
        text = _clean_cell(li.get_text())
        if text and len(text) > 2:
            items.append(text)
    return items[:200]  # cap


def _extract_text(soup: BeautifulSoup, max_chars: int = 6000) -> str:
    """Extract readable plain text from page."""
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[… ditruncate …]"
    return text


def _extract_json_ld(soup: BeautifulSoup) -> list[dict]:
    """Extract JSON-LD structured data from <script type='application/ld+json'>."""
    results = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            results.append(data)
        except Exception:
            pass
    return results


# ── Core fetch & parse ─────────────────────────────────────────────────────

async def fetch_and_parse(url: str) -> dict:
    """
    Fetch URL and extract all structured data.

    Returns:
    {
        "url": str,
        "title": str,
        "tables": [...],       # list of table dicts
        "lists": [...],        # flat list of li items
        "text": str,           # plain text
        "json_ld": [...],      # JSON-LD blocks
        "raw_json": dict|None, # if response was JSON
        "error": str|None,
        "fetched_at": str,
    }
    """
    result = {
        "url": url,
        "title": "",
        "tables": [],
        "lists": [],
        "text": "",
        "json_ld": [],
        "raw_json": None,
        "error": None,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}"
        return result
    except Exception as e:
        result["error"] = str(e)
        return result

    ct = resp.headers.get("content-type", "")

    # ── JSON response ──────────────────────────────────────────────────────
    if "application/json" in ct:
        try:
            result["raw_json"] = resp.json()
        except Exception:
            result["text"] = resp.text[:5000]
        return result

    # ── HTML response (parse in thread to avoid blocking event loop) ──────────────────────────────────────────────────────────────────────────────────
    html_text = resp.text
    def _parse() -> None:
        soup = BeautifulSoup(html_text, "html.parser")
        title_tag = soup.find("title")
        result["title"] = title_tag.get_text(strip=True) if title_tag else url
        result["tables"]  = _extract_tables(soup)
        result["lists"]   = _extract_lists(soup)
        result["text"]    = _extract_text(soup)
        result["json_ld"] = _extract_json_ld(soup)

    await asyncio.to_thread(_parse)
    return result


# ── Save helpers ───────────────────────────────────────────────────────────

def save_table_csv(rows: list[dict], name: str) -> Path:
    """Save a list of dicts as CSV in the scraped output folder."""
    path = _BASE_DIR / f"{name}.csv"
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return path
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def save_json_data(data: Any, name: str) -> Path:
    """Save arbitrary data as JSON."""
    path = _BASE_DIR / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_text(text: str, name: str) -> Path:
    """Save plain text."""
    path = _BASE_DIR / f"{name}.txt"
    path.write_text(text, encoding="utf-8")
    return path


# ── Local dataset listing & search ────────────────────────────────────────

def list_datasets() -> list[dict]:
    """List all saved datasets in outputs/scraped/."""
    files = sorted(_BASE_DIR.glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files:
        stat = f.stat()
        size_kb = round(stat.st_size / 1024, 1)
        out.append({
            "name": f.name,
            "stem": f.stem,
            "ext":  f.suffix,
            "size_kb": size_kb,
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return out


def load_dataset(filename: str) -> tuple[str, list[dict] | dict | str | None]:
    """
    Load a saved dataset by filename or stem.
    Returns (type, data): type in ('csv','json','text','unknown')
    """
    # Try exact match first, then stem match
    candidates = list(_BASE_DIR.glob(f"{filename}")) + list(_BASE_DIR.glob(f"{filename}.*"))
    if not candidates:
        # try case-insensitive
        candidates = [f for f in _BASE_DIR.iterdir() if f.stem.lower() == filename.lower()]

    if not candidates:
        return ("unknown", None)

    path = candidates[0]
    ext = path.suffix.lower()

    try:
        if ext == ".csv":
            rows = []
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(dict(row))
            return ("csv", rows)

        elif ext == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            return ("json", data)

        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            return ("text", text)
    except Exception as e:
        return ("unknown", None)


def search_dataset(filename: str, query: str, max_results: int = 30) -> str:
    """
    Search inside a saved CSV/JSON dataset.
    Returns formatted text result.
    """
    dtype, data = load_dataset(filename)

    if dtype == "unknown" or data is None:
        return f"❌ File `{filename}` tidak ditemukan di datasets lokal."

    q = query.lower().strip()

    if dtype == "csv":
        rows: list[dict] = data  # type: ignore
        matched = []
        for row in rows:
            if any(q in str(v).lower() for v in row.values()):
                matched.append(row)
        if not matched:
            return f"🔍 Tidak ada hasil untuk *{query}* di `{filename}`"

        lines = [f"🔍 *Search hasil* `{filename}` — query: _{query}_\n({len(matched)} baris cocok)\n"]
        for row in matched[:max_results]:
            lines.append("  " + " | ".join(f"{k}: {v}" for k, v in row.items() if v))
        if len(matched) > max_results:
            lines.append(f"  _…dan {len(matched)-max_results} baris lainnya._")
        return "\n".join(lines)

    elif dtype == "json":
        # Flatten JSON for search
        text = json.dumps(data, ensure_ascii=False)
        if q not in text.lower():
            return f"🔍 Query *{query}* tidak ditemukan di `{filename}`"
        # Return snippet around match
        idx = text.lower().find(q)
        snippet = text[max(0, idx-100):idx+300]
        return f"🔍 *Match di* `{filename}`:\n```\n{snippet}\n```"

    else:
        text: str = data  # type: ignore
        if q not in text.lower():
            return f"🔍 Query *{query}* tidak ditemukan di `{filename}`"
        lines_all = text.splitlines()
        matched = [l for l in lines_all if q in l.lower()][:max_results]
        return (
            f"🔍 *Match di* `{filename}` — {len(matched)} baris:\n"
            + "\n".join(f"  {l}" for l in matched)
        )


def show_dataset(filename: str, max_rows: int = 20) -> str:
    """Show first N rows of a saved dataset."""
    dtype, data = load_dataset(filename)

    if dtype == "unknown" or data is None:
        return f"❌ File `{filename}` tidak ditemukan."

    if dtype == "csv":
        rows: list[dict] = data  # type: ignore
        if not rows:
            return f"📄 `{filename}` kosong."
        headers = list(rows[0].keys())
        lines = [f"📄 *{filename}* ({len(rows)} baris total)\n",
                 "  " + " | ".join(f"**{h}**" for h in headers[:6])]
        for row in rows[:max_rows]:
            lines.append("  " + " | ".join(str(row.get(h, ""))[:30] for h in headers[:6]))
        if len(rows) > max_rows:
            lines.append(f"  _…{len(rows)-max_rows} baris lagi. Gunakan /datasearch untuk filter._")
        return "\n".join(lines)

    elif dtype == "json":
        text = json.dumps(data, ensure_ascii=False, indent=2)
        snippet = text[:2000]
        if len(text) > 2000:
            snippet += "\n\n[… ditruncate …]"
        return f"📄 *{filename}*:\n```json\n{snippet}\n```"

    else:
        text: str = data  # type: ignore
        snippet = text[:2000]
        if len(text) > 2000:
            snippet += "\n\n[… ditruncate …]"
        return f"📄 *{filename}*:\n```\n{snippet}\n```"


# ── High-level scrape + format ─────────────────────────────────────────────

async def scrape_and_format(
    url: str,
    *,
    save: bool = False,
    table_index: int = 0,
) -> tuple[str, list[Path]]:
    """
    Scrape a URL and return (formatted_text_reply, list_of_saved_paths).

    formatted_text_reply is ready to send to Telegram.
    """
    data = await fetch_and_parse(url)
    saved_paths: list[Path] = []

    if data["error"]:
        return (f"❌ Gagal fetch `{url}`:\n`{data['error']}`", [])

    title = data["title"] or url
    fname = _safe_filename(url)
    lines = [f"🌐 *{title}*\n`{url}`\n"]

    # ── JSON response ──────────────────────────────────────────────────────
    if data["raw_json"] is not None:
        rj = data["raw_json"]
        if isinstance(rj, list):
            lines.append(f"📊 JSON array: *{len(rj)} items*")
            if rj and isinstance(rj[0], dict):
                lines.append(f"Fields: `{', '.join(list(rj[0].keys())[:8])}`")
            preview = json.dumps(rj[:3], ensure_ascii=False, indent=2)[:800]
            lines.append(f"```json\n{preview}\n```")
            if save:
                p = save_json_data(rj, fname)
                saved_paths.append(p)
                lines.append(f"\n💾 Disimpan: `{p.name}` ({round(p.stat().st_size/1024,1)} KB)")
        else:
            preview = json.dumps(rj, ensure_ascii=False, indent=2)[:1000]
            lines.append(f"```json\n{preview}\n```")
            if save:
                p = save_json_data(rj, fname)
                saved_paths.append(p)
                lines.append(f"\n💾 Disimpan: `{p.name}`")
        return ("\n".join(lines), saved_paths)

    # ── Tables ─────────────────────────────────────────────────────────────
    tables = data["tables"]
    if tables:
        lines.append(f"📊 Ditemukan *{len(tables)} tabel*\n")
        for i, tbl in enumerate(tables[:3], 1):
            rc = tbl["row_count"]
            hdrs = tbl["headers"]
            lines.append(f"*Tabel {i}* — {rc} baris")
            if hdrs:
                lines.append(f"  Kolom: `{', '.join(hdrs[:8])}`")

            # Show first 5 rows
            for row in tbl["rows"][:5]:
                cells = list(row.values())
                lines.append("  " + " | ".join(str(c)[:25] for c in cells[:5]))
            if rc > 5:
                lines.append(f"  _…{rc-5} baris lagi_")
            lines.append("")

            if save:
                p = save_table_csv(tbl["rows"], f"{fname}_tabel{i}")
                saved_paths.append(p)
                lines.append(f"💾 Tabel {i} disimpan: `{p.name}` ({round(p.stat().st_size/1024,1)} KB)")

    # ── Lists ──────────────────────────────────────────────────────────────
    elif data["lists"]:
        items = data["lists"]
        lines.append(f"📋 Ditemukan *{len(items)} item list*\n")
        for item in items[:15]:
            lines.append(f"  • {item[:100]}")
        if len(items) > 15:
            lines.append(f"  _…{len(items)-15} item lagi_")

        if save:
            text_out = "\n".join(items)
            p = save_text(text_out, f"{fname}_list")
            saved_paths.append(p)
            lines.append(f"\n💾 Disimpan: `{p.name}`")

    # ── Plain text fallback ────────────────────────────────────────────────
    else:
        text = data["text"]
        lines.append(f"📄 *Teks halaman* ({len(text)} karakter)\n")
        lines.append(text[:1500])
        if len(text) > 1500:
            lines.append("\n_[…ditruncate…]_")

        if save:
            p = save_text(text, fname)
            saved_paths.append(p)
            lines.append(f"\n💾 Disimpan: `{p.name}`")

    # ── JSON-LD ────────────────────────────────────────────────────────────
    if data["json_ld"] and not tables:
        lines.append(f"\n🔖 JSON-LD schema: `{len(data['json_ld'])} blok`")

    if not save and (tables or data["lists"]):
        lines.append(
            "\n_💡 Tip: Tambahkan `--save` untuk simpan ke file lokal, "
            "lalu gunakan /datasearch untuk cari data tanpa internet._"
        )

    return ("\n".join(lines), saved_paths)


# ── Web Crawler ────────────────────────────────────────────────────────────

def _extract_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Extract all absolute internal links from a page."""
    from urllib.parse import urljoin, urldefrag
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc

    links: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url, href)
        full, _ = urldefrag(full)  # strip fragment
        parsed = urlparse(full)
        # only http/https and same domain
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc != base_domain:
            continue
        if full not in seen:
            seen.add(full)
            links.append(full)
    return links


async def crawl_and_format(
    start_url: str,
    *,
    max_pages: int = 50,
    depth: int = 5,
    save: bool = False,
) -> tuple[str, list[Path]]:
    """
    Crawl from start_url BFS, fetching each level concurrently.
    BeautifulSoup parsing is offloaded to a thread pool to avoid blocking
    the Telegram event loop for other users.
    Returns (formatted_report, saved_paths).
    """
    visited:  set[str]  = set()
    results:  list[dict] = []
    saved_paths: list[Path] = []

    # BFS level-by-level so we can fetch each level concurrently
    current_level: list[tuple[str, int]] = [(start_url, 0)]

    async def _fetch_one(client: httpx.AsyncClient, url: str, cur_depth: int) -> dict:
        """Fetch one URL and parse HTML in a thread. Returns a result dict."""
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception as e:
            return {"url": url, "title": "", "error": str(e), "depth": cur_depth, "links": []}

        ct = resp.headers.get("content-type", "")
        if "html" not in ct:
            return {"url": url, "title": f"[non-HTML: {ct[:30]}]", "error": None, "depth": cur_depth, "links": []}

        html_text = resp.text
        out: dict = {"url": url, "depth": cur_depth, "error": None}

        def _parse() -> None:
            soup = BeautifulSoup(html_text, "html.parser")
            title_tag = soup.find("title")
            out["title"]   = title_tag.get_text(strip=True) if title_tag else url
            out["snippet"] = _extract_text(soup, max_chars=400)[:300].replace("\n", " ").strip()
            out["links"]   = _extract_links(soup, url)

        await asyncio.to_thread(_parse)
        return out

    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True
    ) as client:
        while current_level and len(results) < max_pages:
            # Filter out already-visited, cap to remaining budget
            budget = max_pages - len(results)
            to_fetch = []
            for url, d in current_level:
                if url not in visited and len(to_fetch) < budget:
                    visited.add(url)
                    to_fetch.append((url, d))

            if not to_fetch:
                break

            # Fetch all URLs in this level concurrently
            page_results = await asyncio.gather(
                *(_fetch_one(client, url, d) for url, d in to_fetch),
                return_exceptions=False,
            )

            next_level: list[tuple[str, int]] = []
            for r in page_results:
                results.append(r)
                if not r.get("error") and r["depth"] < depth:
                    for link in r.get("links", []):
                        if link not in visited:
                            next_level.append((link, r["depth"] + 1))

            current_level = next_level

    # ── Save ──────────────────────────────────────────────────────────────
    if save:
        parsed = urlparse(start_url)
        fname = _safe_filename(start_url)
        # Save as JSON (full)
        p = save_json_data(results, f"crawl_{fname}")
        saved_paths.append(p)
        # Also save links as flat CSV
        link_rows = [
            {"page_url": r["url"], "page_title": r["title"], "link": lnk}
            for r in results for lnk in r.get("links", [])
        ]
        if link_rows:
            p2 = save_table_csv(link_rows, f"crawl_links_{fname}")
            saved_paths.append(p2)

    # ── Format output ──────────────────────────────────────────────────────
    parsed_base = urlparse(start_url)
    lines = [
        f"🕸️ *Crawl Report: {parsed_base.netloc}*",
        f"`{start_url}`",
        f"_Ditemukan {len(results)} halaman (depth ≤ {depth}, max {max_pages})_\n",
    ]

    ok_pages    = [r for r in results if not r.get("error")]
    error_pages = [r for r in results if r.get("error")]

    for r in ok_pages:
        depth_icon = "🔵" if r["depth"] == 0 else ("🟢" if r["depth"] == 1 else "⚪")
        lines.append(f"{depth_icon} *{r['title'][:60]}*")
        lines.append(f"  `{r['url'][:80]}`")
        if r.get("snippet"):
            lines.append(f"  _{r['snippet'][:150]}_")
        lines.append(f"  🔗 {len(r['links'])} link ditemukan")
        lines.append("")

    if error_pages:
        lines.append(f"⚠️ *{len(error_pages)} halaman gagal di-fetch:*")
        for r in error_pages[:5]:
            lines.append(f"  • `{r['url'][:60]}` — {r['error']}")
        lines.append("")

    if save and saved_paths:
        for p in saved_paths:
            lines.append(f"💾 Disimpan: `{p.name}` ({round(p.stat().st_size/1024,1)} KB)")
    elif not save:
        lines.append(
            "_💡 Tip: Tambahkan `--save` untuk simpan semua data + link ke file lokal._"
        )

    return ("\n".join(lines), saved_paths)


# ── Entity/person search (Wikidata + Wikipedia) ────────────────────────────

# Wikidata property ID → (display label, URL template)
_SOCIAL_PROPS: dict[str, tuple[str, str]] = {
    "P2002": ("Twitter/X",   "https://x.com/{}"),
    "P2003": ("Instagram",   "https://instagram.com/{}"),
    "P2013": ("Facebook",    "https://facebook.com/{}"),
    "P4003": ("Facebook ID", "https://facebook.com/{}"),
    "P7085": ("TikTok",      "https://tiktok.com/@{}"),
    "P2397": ("YouTube",     "https://youtube.com/channel/{}"),
    "P856":  ("Website",     "{}"),
}

_BIRTH_PROP    = "P569"   # date of birth
_POSITION_PROP = "P39"    # position held
_EDUCATION_PROP = "P69"   # educated at (alma mater)
_DEGREE_PROP    = "P512"  # academic degree (qualifier on P69 claim)

# ── PDDikti (Pangkalan Data Pendidikan Tinggi) — Kemdiktisaintek ───────────
_PDDIKTI_BASE = "https://api-pddikti.kemdiktisaintek.go.id"
_PDDIKTI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://pddikti.kemdiktisaintek.go.id/",
    "Origin": "https://pddikti.kemdiktisaintek.go.id",
}


def _parse_pddikti_status(raw: str) -> str:
    """
    Parse PDDikti 'status_saat_ini' into a readable string.
    "Lulus-2020/2021 Genap" → "Lulus (2020/2021 Genap)"
    "Mengajukan pengunduran diri-2016/2017 Ganjil" → "Keluar (2016/2017 Ganjil)"
    """
    if not raw:
        return ""
    _status_map = {
        "lulus":                          "Lulus ✓",
        "aktif":                          "Aktif",
        "mengajukan pengunduran diri":    "Keluar/DO",
        "non aktif":                      "Non Aktif",
        "cuti":                           "Cuti",
        "drop out":                       "Drop Out",
    }
    m = re.match(r"^(.+?)[-–](\d{4}/.+)$", raw)
    if m:
        status_key = m.group(1).strip().lower()
        semester   = m.group(2).strip()
        status_lbl = _status_map.get(status_key, m.group(1).strip().title())
        return f"{status_lbl} ({semester})"
    # strip trailing dash/space with no semester
    raw = re.sub(r"[-–]\s*$", "", raw).strip()
    # no semester suffix
    key = raw.strip().lower()
    return _status_map.get(key, raw.strip().title())


async def _pddikti_education(name: str, client: httpx.AsyncClient) -> list[str]:
    """
    Query PDDikti for people named *name*.
    Fetches /pencarian/all/ then concurrently fetches /detail/mhs/ for
    status (Aktif/Lulus/Keluar) and jenjang (Sarjana/Magister/etc.).
    Returns [] if not found or API is unavailable.
    """
    try:
        r = await client.get(
            f"{_PDDIKTI_BASE}/pencarian/all/{quote(name)}",
            headers=_PDDIKTI_HEADERS,
            timeout=12.0,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        results: list[str] = []
        seen: set[str] = set()

        # ── Mahasiswa: fetch detail concurrently (top 5) ───────────────
        async def _mhs_detail(mhs: dict) -> dict:
            mhs_id = mhs.get("id", "")
            if not mhs_id:
                return mhs
            try:
                dr = await client.get(
                    f"{_PDDIKTI_BASE}/detail/mhs/{quote(mhs_id, safe='')}",
                    headers=_PDDIKTI_HEADERS,
                    timeout=10.0,
                )
                if dr.status_code == 200:
                    return {**mhs, **dr.json()}
            except Exception:
                pass
            return mhs

        mhs_list = (data.get("mahasiswa") or [])[:5]
        detailed  = await asyncio.gather(*[_mhs_detail(m) for m in mhs_list])

        for m in detailed:
            prodi   = (m.get("prodi") or m.get("nama_prodi") or "").title()
            pt      = (m.get("nama_pt") or "").title()
            jenjang = (m.get("jenjang") or "").title()
            status  = _parse_pddikti_status(m.get("status_saat_ini") or "")
            if not (prodi and pt):
                continue
            meta_parts = [p for p in (jenjang, status) if p] or ["Mhs"]
            entry = f"{prodi} — {pt} _({', '.join(meta_parts)})_"
            if entry not in seen:
                results.append(entry)
                seen.add(entry)

        # ── Dosen (list only, no confirmed detail endpoint) ────────────
        for d in (data.get("dosen") or [])[:3]:
            prodi = (d.get("nama_prodi") or "").title()
            pt    = (d.get("nama_pt")   or "").title()
            if prodi and pt:
                entry = f"{prodi} — {pt} _(Dosen)_"
                if entry not in seen:
                    results.append(entry)
                    seen.add(entry)

        return results
    except Exception as exc:
        logger.warning(f"PDDikti error: {exc}")
        return []


def is_url_or_domain(s: str) -> bool:
    """Return True if s looks like a URL or bare domain, False if it's a name/phrase."""
    if s.startswith(("http://", "https://")):
        return True
    # bare domain: labels separated by dots, ending with a TLD — no spaces
    return bool(re.match(
        r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?'
        r'(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*'
        r'\.[a-zA-Z]{2,}$',
        s,
    ))


async def search_entity(name: str) -> str:
    """
    Search for a person/organization/entity by name.

    Pipeline:
      1. Wikidata entity search → Q-ID, label, description
      2. Wikipedia REST API (id then en) → bio extract
      3. Wikidata entity claims → social media, birth date, positions
      4. Return Telegram-formatted Markdown string
    """
    async with httpx.AsyncClient(
        headers=_WIKI_HEADERS, timeout=_TIMEOUT, follow_redirects=True
    ) as client:

        # ── Step 1: Wikidata entity search ────────────────────────────────
        entity_id    = ""
        entity_label = name
        entity_desc  = ""
        try:
            resp = await client.get(
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbsearchentities",
                    "search": name,
                    "language": "id",
                    "fallbacklanguage": "en",
                    "format": "json",
                    "limit": 5,
                    "type": "item",
                },
            )
            hits = resp.json().get("search", [])
            if hits:
                top = hits[0]
                entity_id    = top["id"]
                entity_label = top.get("label", name)
                entity_desc  = top.get("description", "")
        except Exception as e:
            logger.warning(f"Wikidata search error: {e}")

        if not entity_id:
            # Not in Wikidata — try PDDikti directly
            pddikti_edu = await _pddikti_education(name, client)
            if pddikti_edu:
                lines = [f"👤 *{name}*", ""]
                lines.append(f"🎓 Pendidikan _(sumber: PDDikti/Kemdiktisaintek)_:")
                for e in pddikti_edu:
                    lines.append(f"  • {e}")
                return "\n".join(lines)
            return (
                f"❌ Tidak ditemukan data untuk *{name}* di Wikidata maupun PDDikti.\n\n"
                "_Coba gunakan nama lengkap atau nama resmi._"
            )

        # ── Step 2: Wikipedia summary ──────────────────────────────────────
        wiki_extract = ""
        wiki_page    = ""
        slug = entity_label.replace(" ", "_")
        for lang in ("id", "en"):
            try:
                r = await client.get(
                    f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{slug}"
                )
                if r.status_code == 200:
                    wdata = r.json()
                    extract = wdata.get("extract", "")
                    if extract and len(extract) > 50:
                        wiki_extract = extract[:900]
                        wiki_page = f"https://{lang}.wikipedia.org/wiki/{slug}"
                        break
            except Exception:
                pass

        # ── Step 3: Wikidata entity claims ────────────────────────────────
        social:     dict[str, str] = {}
        positions:  list[str]      = []
        education:  list[str]      = []
        born:       str            = ""
        edu_source: str            = "Wikidata"
        try:
            r = await client.get(
                f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json"
            )
            entity_data = r.json().get("entities", {}).get(entity_id, {})
            claims = entity_data.get("claims", {})

            # Social media & website
            for prop, (label, tmpl) in _SOCIAL_PROPS.items():
                if prop not in claims:
                    continue
                val = (
                    claims[prop][0]
                    .get("mainsnak", {})
                    .get("datavalue", {})
                    .get("value", "")
                )
                if val and isinstance(val, str) and label not in social:
                    url = val if prop == "P856" else tmpl.format(val)
                    social[label] = url

            # Date of birth
            if _BIRTH_PROP in claims:
                time_val = (
                    claims[_BIRTH_PROP][0]
                    .get("mainsnak", {})
                    .get("datavalue", {})
                    .get("value", {})
                )
                if isinstance(time_val, dict):
                    raw = time_val.get("time", "")
                    m = re.match(r"[+-](\d{4})-(\d{2})-(\d{2})", raw)
                    if m:
                        y, mo, d = m.groups()
                        MONTHS = ["","Jan","Feb","Mar","Apr","Mei","Jun",
                                  "Jul","Agu","Sep","Okt","Nov","Des"]
                        try:
                            born = f"{int(d)} {MONTHS[int(mo)]} {y}"
                        except Exception:
                            born = f"{y}-{mo}-{d}"

            # ── Education: Wikidata P69 first, PDDikti fallback ─────────────
            edu_source = "Wikidata"

            edu_entries: list[dict] = []
            if _EDUCATION_PROP in claims:
                for c in claims[_EDUCATION_PROP]:
                    snak = c.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                    if not isinstance(snak, dict) or "id" not in snak:
                        continue
                    quals = c.get("qualifiers", {})

                    # Degree Q-ID from P512 qualifier
                    deg_qid = ""
                    if _DEGREE_PROP in quals:
                        dq = quals[_DEGREE_PROP][0].get("datavalue", {}).get("value", {})
                        if isinstance(dq, dict) and "id" in dq:
                            deg_qid = dq["id"]

                    # Study field Q-ID from P812 qualifier (field of study)
                    field_qid = ""
                    if "P812" in quals:
                        fq = quals["P812"][0].get("datavalue", {}).get("value", {})
                        if isinstance(fq, dict) and "id" in fq:
                            field_qid = fq["id"]

                    # Years from P580 (start) and P582 (end)
                    def _year(qualif_key: str) -> str:
                        if qualif_key not in quals:
                            return ""
                        tv = quals[qualif_key][0].get("datavalue", {}).get("value", {})
                        if isinstance(tv, dict):
                            mm = re.match(r"[+-](\d{4})", tv.get("time", ""))
                            return mm.group(1) if mm else ""
                        return ""

                    edu_entries.append({
                        "inst_qid":  snak["id"],
                        "deg_qid":   deg_qid,
                        "field_qid": field_qid,
                        "start":     _year("P580"),
                        "end":       _year("P582"),
                    })

            # Batch-resolve all institution + degree + field Q-IDs at once
            if edu_entries:
                all_edu_qids = list({
                    qid
                    for e in edu_entries
                    for qid in (e["inst_qid"], e["deg_qid"], e["field_qid"])
                    if qid
                })
                qid_labels: dict[str, str] = {}
                try:
                    lr = await client.get(
                        "https://www.wikidata.org/w/api.php",
                        params={
                            "action": "wbgetentities",
                            "ids": "|".join(all_edu_qids),
                            "props": "labels",
                            "languages": "id|en",
                            "format": "json",
                        },
                    )
                    ldata = lr.json().get("entities", {})
                    for qid in all_edu_qids:
                        lbls = ldata.get(qid, {}).get("labels", {})
                        qid_labels[qid] = (
                            lbls.get("id", {}).get("value")
                            or lbls.get("en", {}).get("value")
                            or qid
                        )
                except Exception:
                    pass

                for e in edu_entries:
                    inst  = qid_labels.get(e["inst_qid"],  e["inst_qid"])
                    deg   = qid_labels.get(e["deg_qid"],   "") if e["deg_qid"]   else ""
                    field = qid_labels.get(e["field_qid"], "") if e["field_qid"] else ""

                    detail_parts = [p for p in (deg, field) if p]
                    detail = f" ({', '.join(detail_parts)})" if detail_parts else ""

                    if e["start"] and e["end"]:
                        years = f" {e['start']}–{e['end']}"
                    elif e["start"]:
                        years = f" {e['start']}–"
                    elif e["end"]:
                        years = f" –{e['end']}"
                    else:
                        years = ""

                    education.append(f"{inst}{detail}{years}")

            # If Wikidata has no education data, try PDDikti as fallback
            if not education:
                pddikti_edu = await _pddikti_education(name, client)
                if pddikti_edu:
                    education = pddikti_edu
                    edu_source = "PDDikti/Kemdiktisaintek"

            # Positions held (P39) — resolve Q-IDs to labels
            if _POSITION_PROP in claims:
                qids = []
                for c in claims[_POSITION_PROP][:6]:
                    snak = c.get("mainsnak", {}).get("datavalue", {}).get("value", {})
                    if isinstance(snak, dict) and "id" in snak:
                        qids.append(snak["id"])
                if qids:
                    try:
                        lr = await client.get(
                            "https://www.wikidata.org/w/api.php",
                            params={
                                "action": "wbgetentities",
                                "ids": "|".join(qids),
                                "props": "labels",
                                "languages": "id|en",
                                "format": "json",
                            },
                        )
                        ldata = lr.json().get("entities", {})
                        for qid in qids:
                            lbls = ldata.get(qid, {}).get("labels", {})
                            lbl = (
                                lbls.get("id", {}).get("value")
                                or lbls.get("en", {}).get("value")
                                or qid
                            )
                            positions.append(lbl)
                    except Exception:
                        pass

        except Exception as e:
            logger.warning(f"Wikidata claims error: {e}")

    # ── Format output ──────────────────────────────────────────────────────
    lines: list[str] = []

    lines.append(f"👤 *{entity_label}*")
    if entity_desc:
        lines.append(f"_{entity_desc}_")
    lines.append("")

    if born:
        lines.append(f"📅 Lahir: {born}")

    if positions:
        lines.append("🏛 Jabatan/Posisi:")
        for p in positions:
            lines.append(f"  • {p}")

    if education:
        lines.append(f"🎓 Pendidikan _(sumber: {edu_source})_:")
        for e in education:
            lines.append(f"  • {e}")

    if wiki_extract:
        lines.append("")
        lines.append(wiki_extract)

    lines.append("")
    if social:
        lines.append("📱 *Akun & Link Resmi:*")
        for platform, url in social.items():
            lines.append(f"  • {platform}: {url}")
    else:
        lines.append("_ℹ️ Tidak ada akun resmi terdaftar di Wikidata._")

    lines.append("")
    lines.append(f"🔗 [Wikidata](https://www.wikidata.org/wiki/{entity_id})")
    if wiki_page:
        lines.append(f"🔗 [Wikipedia]({wiki_page})")

    return "\n".join(lines)
