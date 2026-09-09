"""
dpr_scraper.py - Scraper lengkap Anggota DPR RI 2024-2029 dari dpr.go.id
Menggunakan Playwright (browser headless) untuk bypass WAF/403.

Output: dpr_scraper_raw.json + dpr_indonesia_full.csv + dpr_indonesia_full.txt

Cara pakai:
  python dpr_scraper.py              # scrape semua fraksi
  python dpr_scraper.py --headless   # tanpa jendela browser (default)
  python dpr_scraper.py --show       # tampilkan jendela browser (debug)
  python dpr_scraper.py --limit 20   # hanya ambil N anggota (test)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

OUT_DIR = Path(__file__).parent
CSV_FIELDS = ["nama", "gelar_depan", "gelar_belakang", "fraksi", "dapil", "provinsi", "komisi", "jabatan", "url_profil"]

KOMISI_DPR = {
    "I":    "Pertahanan, Intelijen, Luar Negeri, Komunikasi & Informatika",
    "II":   "Pemerintahan Dalam Negeri, Otonomi Daerah, Aparatur Negara, Agraria",
    "III":  "Hukum, HAM, Keamanan",
    "IV":   "Pertanian, Perkebunan, Kehutanan, Kelautan, Perikanan, Pangan",
    "V":    "Perhubungan, Pekerjaan Umum, Perumahan Rakyat, Telekomunikasi",
    "VI":   "Perdagangan, Perindustrian, Investasi, Koperasi, BUMN",
    "VII":  "Energi, Riset & Teknologi, Lingkungan Hidup",
    "VIII": "Agama, Sosial, Pemberdayaan Perempuan",
    "IX":   "Ketenagakerjaan, Kependudukan, Kesehatan",
    "X":    "Pendidikan, Pemuda, Olahraga, Pariwisata",
    "XI":   "Keuangan, Perbankan, Perencanaan Pembangunan Nasional",
}

# DPR Periode X = id_periode 20 (2024-2029), id_periode 21 if they renumbered
# Will try both
PERIODE_IDS = [20, 21, 19]
BASE_URL = "https://www.dpr.go.id"


def make_browser(playwright, headless: bool):
    browser = playwright.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-web-security",
        ],
    )
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="id-ID",
        timezone_id="Asia/Jakarta",
        extra_http_headers={
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    # Hide automation flags
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
    """)
    return browser, context


def find_working_periode(page) -> int | None:
    """Cari id_periode yang valid untuk 2024-2029"""
    for pid in PERIODE_IDS:
        url = f"{BASE_URL}/anggota/index/id_periode/{pid}"
        logger.info(f"Mencoba periode {pid}: {url}")
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=20000)
            status = resp.status if resp else 0
            logger.info(f"  -> Status {status}")
            if status == 200:
                # Cek apakah ada data anggota
                content = page.content()
                if "anggota" in content.lower() and len(content) > 5000:
                    logger.info(f"  -> Periode {pid} VALID!")
                    return pid
                else:
                    logger.info(f"  -> Konten tidak valid")
        except Exception as e:
            logger.warning(f"  -> Error: {e}")
        time.sleep(1)
    return None


def parse_anggota_list(page) -> list[dict]:
    """Parse daftar anggota dari halaman listing"""
    members = []
    try:
        # Tunggu tabel atau grid anggota
        page.wait_for_selector(
            "table, .anggota-item, .card-anggota, [class*='member'], [class*='anggota']",
            timeout=10000
        )
    except Exception:
        logger.warning("Tidak ada selector anggota ditemukan")

    # Coba berbagai selector untuk nama anggota
    selectors = [
        "table tbody tr",
        ".anggota-item",
        ".card-anggota",
        "[class*='member-name']",
        "a[href*='/anggota/view']",
        "a[href*='/anggota/detail']",
        ".nama-anggota",
    ]

    found_links = []
    for sel in selectors:
        try:
            els = page.query_selector_all(sel)
            if els:
                logger.info(f"Selector '{sel}' menemukan {len(els)} elemen")
                for el in els:
                    href = el.get_attribute("href") or ""
                    text = el.inner_text().strip()
                    if href and ("/anggota/view" in href or "/anggota/detail" in href):
                        found_links.append({"nama_raw": text, "url": href})
                    elif el.tag_name() == "tr":
                        cells = el.query_selector_all("td")
                        if cells and len(cells) >= 2:
                            a = el.query_selector("a")
                            url = a.get_attribute("href") if a else ""
                            row_data = [c.inner_text().strip() for c in cells]
                            found_links.append({
                                "nama_raw": row_data[0] if row_data else "",
                                "url": url or "",
                                "cells": row_data,
                            })
                if found_links:
                    break
        except Exception as e:
            logger.debug(f"Selector {sel} error: {e}")

    return found_links


def scrape_profile_page(page, url: str) -> dict:
    """Scrape halaman profil individual anggota"""
    result = {"url_profil": url}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        time.sleep(0.5)

        # Try to extract name, fraksi, dapil, komisi
        content = page.content()

        # Berbagai strategi ekstraksi
        import re

        # Nama
        name_patterns = [
            r'<h1[^>]*>([^<]{5,80})</h1>',
            r'class="nama[^"]*"[^>]*>([^<]{5,80})<',
            r'"name"\s*:\s*"([^"]{5,80})"',
        ]
        for pat in name_patterns:
            m = re.search(pat, content, re.I)
            if m:
                result["nama"] = m.group(1).strip()
                break

        # Fraksi
        fraksi_pat = r'(?:fraksi|partai)[^:]*:\s*([A-Z][^<\n]{3,40})'
        m = re.search(fraksi_pat, content, re.I)
        if m:
            result["fraksi_raw"] = m.group(1).strip()

        # Dapil
        dapil_pat = r'(?:dapil|daerah pemilihan)[^:]*:\s*([^<\n]{5,60})'
        m = re.search(dapil_pat, content, re.I)
        if m:
            result["dapil"] = m.group(1).strip()

        # Komisi
        komisi_pat = r'(?:komisi|alat kelengkapan)[^:]*:\s*([^<\n]{3,60})'
        m = re.search(komisi_pat, content, re.I)
        if m:
            result["komisi_raw"] = m.group(1).strip()

        logger.debug(f"Profil: {result.get('nama','?')} | {result.get('fraksi_raw','?')}")
    except Exception as e:
        logger.warning(f"Error profil {url}: {e}")
    return result


def scrape_all(headless: bool, limit: int | None) -> list[dict]:
    """Main scraping function"""
    from playwright.sync_api import sync_playwright

    all_members = []
    with sync_playwright() as pw:
        browser, context = make_browser(pw, headless=headless)
        page = context.new_page()

        # Step 1: Load homepage to get cookies
        logger.info("Memuat homepage DPR RI...")
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)
            logger.info(f"Homepage loaded, title: {page.title()[:60]}")
        except Exception as e:
            logger.error(f"Gagal load homepage: {e}")
            browser.close()
            return []

        # Step 2: Find working periode
        working_periode = find_working_periode(page)
        if not working_periode:
            # Try direct anggota URL without periode
            logger.info("Coba URL /anggota langsung...")
            try:
                resp = page.goto(f"{BASE_URL}/anggota", wait_until="domcontentloaded", timeout=20000)
                logger.info(f"  /anggota -> {resp.status if resp else '?'}")
            except Exception as e:
                logger.error(f"Gagal: {e}")

        # Step 3: Get page content for debugging
        current_url = page.url
        content = page.content()
        logger.info(f"Current URL: {current_url}")
        logger.info(f"Content len: {len(content)}")
        logger.info(f"Content sample: {content[:500]}")

        # Step 4: Try to find member links
        anggota_links = parse_anggota_list(page)
        logger.info(f"Ditemukan {len(anggota_links)} link anggota di halaman listing")

        if not anggota_links:
            # Last resort: look at all links containing 'anggota'
            all_links = page.query_selector_all("a")
            for link in all_links:
                href = link.get_attribute("href") or ""
                if "anggota" in href.lower():
                    text = link.inner_text().strip()
                    anggota_links.append({"nama_raw": text, "url": href})
            logger.info(f"Setelah fallback: {len(anggota_links)} link anggota")

        # Step 5: Scrape profiles if we have links
        if limit:
            anggota_links = anggota_links[:limit]

        for i, link_data in enumerate(anggota_links, 1):
            url = link_data.get("url", "")
            if url and not url.startswith("http"):
                url = BASE_URL + url
            logger.info(f"[{i}/{len(anggota_links)}] Scraping: {url[:80]}")
            profile = scrape_profile_page(page, url) if url else {}
            profile.update({k: v for k, v in link_data.items() if k not in profile})
            all_members.append(profile)
            time.sleep(0.5)

        browser.close()
    return all_members


def save_results(members: list[dict], out_dir: Path) -> None:
    # Save raw JSON
    raw_path = out_dir / "dpr_scraper_raw.json"
    raw_path.write_text(json.dumps(members, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Raw JSON: {raw_path}")

    # Save CSV
    csv_path = out_dir / "dpr_indonesia_full.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        # Header
        all_keys = set()
        for m in members:
            all_keys.update(m.keys())
        headers = sorted(all_keys)
        w.writerow(headers)
        for m in members:
            w.writerow([m.get(h, "") for h in headers])
    logger.info(f"CSV: {csv_path} ({len(members)} anggota)")

    # Summary
    txt_path = out_dir / "dpr_scraper_log.txt"
    lines = [
        f"Total scraped: {len(members)}",
        f"",
        "Sample data:",
    ]
    for m in members[:10]:
        lines.append(f"  {m}")
    txt_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Scraper Anggota DPR RI 2024-2029")
    parser.add_argument("--show", action="store_true", help="Tampilkan browser (debug)")
    parser.add_argument("--limit", type=int, help="Batas jumlah anggota yang di-scrape (test)")
    args = parser.parse_args()

    headless = not args.show

    logger.info(f"Memulai scraping DPR RI... headless={headless}")
    members = scrape_all(headless=headless, limit=args.limit)

    if members:
        save_results(members, OUT_DIR)
        logger.info(f"\nSELESAI: {len(members)} anggota berhasil di-scrape")
    else:
        logger.warning("Tidak ada data yang berhasil di-scrape")
        # Show debug info
        logger.info("Coba jalankan dengan --show untuk melihat browser secara visual")


if __name__ == "__main__":
    main()
