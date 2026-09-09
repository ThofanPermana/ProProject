"""
sekolah_collector.py - Kumpulkan data seluruh sekolah di Indonesia.
Sumber: api-sekolah-indonesia.vercel.app (data Kemdikbud, tanpa API key)
Total: +-215.000 sekolah (TK, SD, SMP, SMA, SMK, SLB, MI, MTs, MA, MAK)

Output:
  sekolah_indonesia.csv       - data lengkap (Excel/Sheets)
  sekolah_indonesia.txt       - ringkasan mudah dibaca
  sekolah_indonesia_log.txt   - log proses

Cara pakai:
  python sekolah_collector.py
  python sekolah_collector.py --jenjang SD SMP SMA
  python sekolah_collector.py --resume
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# Logging ke stdout + file
LOG_FILE = Path("sekolah_indonesia_log.txt")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

API_BASE  = "https://api-sekolah-indonesia.vercel.app/sekolah"
PAGE_SIZE = 100
DELAY     = 0.2
TIMEOUT   = 30

JENJANG_PATH = {
    "TK":  "/tk",
    "SD":  "/sd",
    "SMP": "/smp",
    "SMA": "/sma",
    "SMK": "/smk",
    "SLB": "/slb",
    "MI":  "/mi",
    "MTs": "/mts",
    "MA":  "/ma",
    "MAK": "/mak",
}

CSV_FIELDS = [
    "npsn", "nama", "jenjang", "status",
    "provinsi", "kab_kota", "kecamatan", "alamat",
    "lintang", "bujur",
]

STATUS_MAP = {"N": "Negeri", "S": "Swasta"}


def init_csv(path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()


def append_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writerows(rows)


def normalize(raw: dict) -> dict:
    return {
        "npsn":      raw.get("npsn", "").strip(),
        "nama":      raw.get("sekolah", "").strip(),
        "jenjang":   raw.get("bentuk", "").strip(),
        "status":    STATUS_MAP.get(raw.get("status", ""), raw.get("status", "")),
        "provinsi":  raw.get("propinsi", "").strip().replace("Prov. ", ""),
        "kab_kota":  raw.get("kabupaten_kota", "").strip(),
        "kecamatan": raw.get("kecamatan", "").strip(),
        "alamat":    raw.get("alamat_jalan", "").strip(),
        "lintang":   raw.get("lintang", "").strip(),
        "bujur":     raw.get("bujur", "").strip(),
    }


def fetch_page(client: httpx.Client, suffix: str, page: int) -> tuple[list[dict], int]:
    try:
        r = client.get(
            f"{API_BASE}{suffix}",
            params={"page": page, "perPage": PAGE_SIZE},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        rows  = data.get("dataSekolah", [])
        total = int(data.get("total_data", 0))
        total_pages = max(1, -(-total // PAGE_SIZE))
        return rows, total_pages
    except Exception as e:
        logger.warning(f"Gagal halaman {page} {suffix}: {e}")
        return [], 0


def write_summary(path: Path, stats: dict) -> None:
    lines = [
        "=" * 60,
        "  DATA SEKOLAH INDONESIA - Sumber: Kemdikbud",
        f"  Diunduh: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        f"\nTOTAL SEKOLAH  : {stats['total']:,}",
        "\nPER JENJANG:",
    ]
    for j, n in sorted(stats["per_jenjang"].items()):
        lines.append(f"  {j:<6}  {n:>8,}")
    lines.append("\nPER PROVINSI (terbanyak ke terkecil):")
    for prov, n in sorted(stats["per_provinsi"].items(), key=lambda x: -x[1]):
        lines.append(f"  {prov:<35}  {n:>7,}")
    lines += [
        "",
        "=" * 60,
        "Buka CSV: Excel -> Data -> From Text/CSV -> encoding UTF-8",
        "=" * 60,
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Ringkasan disimpan ke {path}")


def collect(target_jenjang: list[str] | None = None, resume: bool = False) -> None:
    csv_path = Path("sekolah_indonesia.csv")
    txt_path = Path("sekolah_indonesia.txt")
    jenjang_list = target_jenjang or list(JENJANG_PATH.keys())

    existing_npsn: set[str] = set()
    if resume and csv_path.exists():
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("npsn"):
                    existing_npsn.add(row["npsn"])
        logger.info(f"Resume: {len(existing_npsn):,} sekolah sudah ada, dilanjutkan...")
    else:
        init_csv(csv_path)

    stats: dict = {"total": len(existing_npsn), "per_jenjang": {}, "per_provinsi": {}}

    with httpx.Client(
        headers={"User-Agent": "Mozilla/5.0 SekolahCollector/2.0"},
        follow_redirects=True,
    ) as client:
        for jenjang in jenjang_list:
            suffix = JENJANG_PATH[jenjang]
            logger.info(f"-- Jenjang: {jenjang} ...")

            _, total_pages = fetch_page(client, suffix, 1)
            if total_pages == 0:
                logger.warning(f"  Tidak ada data untuk {jenjang}, skip.")
                continue

            logger.info(f"  Total halaman: {total_pages} (~{total_pages * PAGE_SIZE:,} sekolah)")
            batch: list[dict] = []

            for page in range(1, total_pages + 1):
                rows, _ = fetch_page(client, suffix, page)
                time.sleep(DELAY)

                for raw in rows:
                    npsn = str(raw.get("npsn", "")).strip()
                    if npsn and npsn in existing_npsn:
                        continue
                    norm = normalize(raw)
                    batch.append(norm)
                    if npsn:
                        existing_npsn.add(npsn)
                    stats["total"] += 1
                    stats["per_jenjang"][jenjang] = stats["per_jenjang"].get(jenjang, 0) + 1
                    prov = norm["provinsi"]
                    stats["per_provinsi"][prov]   = stats["per_provinsi"].get(prov, 0) + 1

                if len(batch) >= 500:
                    append_csv(csv_path, batch)
                    logger.info(f"  Halaman {page}/{total_pages} -- total tersimpan: {stats['total']:,}")
                    batch.clear()

            if batch:
                append_csv(csv_path, batch)
                batch.clear()

            logger.info(f"  {jenjang} selesai: {stats['per_jenjang'].get(jenjang, 0):,} sekolah")

    write_summary(txt_path, stats)
    logger.info(f"\nSELESAI -- {stats['total']:,} sekolah disimpan ke {csv_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kumpulkan data sekolah Indonesia dari API Kemdikbud (~215rb sekolah)"
    )
    parser.add_argument(
        "--jenjang", nargs="+",
        choices=list(JENJANG_PATH.keys()),
        help="Filter jenjang. Contoh: --jenjang SD SMP SMA",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Lanjut dari data yang sudah ada (skip duplikat NPSN)",
    )
    args = parser.parse_args()
    collect(target_jenjang=args.jenjang, resume=args.resume)


if __name__ == "__main__":
    main()
