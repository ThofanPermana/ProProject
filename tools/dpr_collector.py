"""
dpr_collector.py - Data Anggota DPR RI Periode 2024-2029 (Periode X)
Sumber: dpr.go.id (data publik, embedded)

Output:
  dpr_indonesia.csv   - data lengkap
  dpr_indonesia.txt   - ringkasan per fraksi/dapil
  dpr_indonesia.json  - format JSON

Cara pakai:
  python dpr_collector.py
  python dpr_collector.py --fraksi PKS PDIP
  python dpr_collector.py --json
  python dpr_collector.py --list
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Data Anggota DPR RI Periode X (2024–2029)
# Total: 580 kursi, 8 fraksi
# Sumber: KPU RI, dpr.go.id
# ──────────────────────────────────────────────────────────────

# Komposisi kursi fraksi (resmi, 580 total, Periode X 2024-2029)
FRAKSI_KURSI = {
    "PDI-P":    110,
    "Golkar":   102,
    "Gerindra":  86,
    "NasDem":    69,
    "PKB":       68,
    "PKS":       53,
    "PAN":       53,
    "Demokrat":  39,
}

# Data anggota DPR RI 2024-2029 (lengkap, sumber: Wikipedia ID)
# 556 dari 580 kursi berhasil diparsing (11 entri PAW tidak terparsing)
# Sumber: https://id.wikipedia.org/wiki/Daftar_anggota_DPR_RI_2024-2029
ANGGOTA_DPR: list[dict] = [
    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Irmawan", "fraksi": "PKB", "dapil": "Aceh I", "provinsi": "Aceh", "komisi": "V", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Jamaluddin Idham", "fraksi": "PDI-P", "dapil": "Aceh I", "provinsi": "Aceh", "komisi": "XIII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Teuku Zulkarnaini Ampon Bang", "fraksi": "Golkar", "dapil": "Aceh I", "provinsi": "Aceh", "komisi": "VII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Muslim Ayub", "fraksi": "NasDem", "dapil": "Aceh I", "provinsi": "Aceh", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Ghufran", "fraksi": "PKS", "dapil": "Aceh I", "provinsi": "Aceh", "komisi": "VI", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Teuku Riefky Harsya", "fraksi": "PAN", "dapil": "Aceh I", "provinsi": "Aceh", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Ruslan Daud", "fraksi": "PKB", "dapil": "Aceh II", "provinsi": "Aceh", "komisi": "V", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "T. A. Khalid", "fraksi": "Gerindra", "dapil": "Aceh II", "provinsi": "Aceh", "komisi": "IV", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Ilham Pangestu", "fraksi": "Golkar", "dapil": "Aceh II", "provinsi": "Aceh", "komisi": "V", "jabatan": "Anggota"},
    {"nama": "Samsul Bahri Tiyong", "fraksi": "Golkar", "dapil": "Aceh II", "provinsi": "Aceh", "komisi": "XIII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Irsan Sosiawan", "fraksi": "NasDem", "dapil": "Aceh II", "provinsi": "Aceh", "komisi": "XII", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Muhammad Nasir Djamil", "fraksi": "PKS", "dapil": "Aceh II", "provinsi": "Aceh", "komisi": "III", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Ashari Tambunan", "fraksi": "PKB", "dapil": "Sumatera Utara I", "provinsi": "Sumatera Utara", "komisi": "VIII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ade Jona Prasetyo", "fraksi": "Gerindra", "dapil": "Sumatera Utara I", "provinsi": "Sumatera Utara", "komisi": "XIII", "jabatan": "Anggota"},
    {"nama": "M. Husni", "fraksi": "Gerindra", "dapil": "Sumatera Utara I", "provinsi": "Sumatera Utara", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Sofyan Tan", "fraksi": "PDI-P", "dapil": "Sumatera Utara I", "provinsi": "Sumatera Utara", "komisi": "X", "jabatan": "Anggota"},
    {"nama": "Yasonna H. Laoly", "fraksi": "PDI-P", "dapil": "Sumatera Utara I", "provinsi": "Sumatera Utara", "komisi": "XIII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Musa Rajekshah", "fraksi": "Golkar", "dapil": "Sumatera Utara I", "provinsi": "Sumatera Utara", "komisi": "V", "jabatan": "Anggota"},
    {"nama": "Meutya Hafid", "fraksi": "Golkar", "dapil": "Sumatera Utara I", "provinsi": "Sumatera Utara", "komisi": "X", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Prananda Surya Paloh", "fraksi": "NasDem", "dapil": "Sumatera Utara I", "provinsi": "Sumatera Utara", "komisi": "I", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Tifatul Sembiring", "fraksi": "PKS", "dapil": "Sumatera Utara I", "provinsi": "Sumatera Utara", "komisi": "VII", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Muhammad Lokot Nasution", "fraksi": "Demokrat", "dapil": "Sumatera Utara I", "provinsi": "Sumatera Utara", "komisi": "V", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Marwan Dasopang", "fraksi": "PKB", "dapil": "Sumatera Utara II", "provinsi": "Sumatera Utara", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Rapidin Simbolon", "fraksi": "PDI-P", "dapil": "Sumatera Utara II", "provinsi": "Sumatera Utara", "komisi": "XIII", "jabatan": "Anggota"},
    {"nama": "Sihar P. H. Sitorus", "fraksi": "PDI-P", "dapil": "Sumatera Utara II", "provinsi": "Sumatera Utara", "komisi": "IX", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Lamhot Sinaga", "fraksi": "Golkar", "dapil": "Sumatera Utara II", "provinsi": "Sumatera Utara", "komisi": "VII", "jabatan": "Anggota"},
    {"nama": "Andar Amin Harahap", "fraksi": "Golkar", "dapil": "Sumatera Utara II", "provinsi": "Sumatera Utara", "komisi": "II", "jabatan": "Anggota"},
    {"nama": "Trinovi Khairani", "fraksi": "Golkar", "dapil": "Sumatera Utara II", "provinsi": "Sumatera Utara", "komisi": "I", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Martin Manurung", "fraksi": "NasDem", "dapil": "Sumatera Utara II", "provinsi": "Sumatera Utara", "komisi": "XI", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Saleh Partaonan Daulay", "fraksi": "PAN", "dapil": "Sumatera Utara II", "provinsi": "Sumatera Utara", "komisi": "VII", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Sabam Sinaga", "fraksi": "Demokrat", "dapil": "Sumatera Utara II", "provinsi": "Sumatera Utara", "komisi": "X", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Sugiat Santoso", "fraksi": "Gerindra", "dapil": "Sumatera Utara III", "provinsi": "Sumatera Utara", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Bob Andika Mamana Sitepu", "fraksi": "PDI-P", "dapil": "Sumatera Utara III", "provinsi": "Sumatera Utara", "komisi": "II", "jabatan": "Anggota"},
    {"nama": "Bane Raja Manalu", "fraksi": "PDI-P", "dapil": "Sumatera Utara III", "provinsi": "Sumatera Utara", "komisi": "VII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Ahmad Doli Kurnia Tandjung", "fraksi": "Golkar", "dapil": "Sumatera Utara III", "provinsi": "Sumatera Utara", "komisi": "II", "jabatan": "Anggota"},
    {"nama": "Delia Pratiwi Br. Sitepu", "fraksi": "Golkar", "dapil": "Sumatera Utara III", "provinsi": "Sumatera Utara", "komisi": "IX", "jabatan": "Anggota"},
    {"nama": "Mangihut Sinaga", "fraksi": "Golkar", "dapil": "Sumatera Utara III", "provinsi": "Sumatera Utara", "komisi": "III", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Rudi Hartono Bangun", "fraksi": "NasDem", "dapil": "Sumatera Utara III", "provinsi": "Sumatera Utara", "komisi": "VI", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Ansory Siregar", "fraksi": "PKS", "dapil": "Sumatera Utara III", "provinsi": "Sumatera Utara", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Nasril Bahar", "fraksi": "PAN", "dapil": "Sumatera Utara III", "provinsi": "Sumatera Utara", "komisi": "VI", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Hinca I. P. Pandjaitan XIII", "fraksi": "Demokrat", "dapil": "Sumatera Utara III", "provinsi": "Sumatera Utara", "komisi": "III", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Rico Alviano S.T.", "fraksi": "PKB", "dapil": "Sumatera Barat I", "provinsi": "Sumatera Barat", "komisi": "XII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Andre Rosiade", "fraksi": "Gerindra", "dapil": "Sumatera Barat I", "provinsi": "Sumatera Barat", "komisi": "VI", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Alex Indra Lukman S.Sos.", "fraksi": "PDI-P", "dapil": "Sumatera Barat I", "provinsi": "Sumatera Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Zigo Rolanda S.E, M.M.", "fraksi": "Golkar", "dapil": "Sumatera Barat I", "provinsi": "Sumatera Barat", "komisi": "V", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Lisda Hendrajoni S.E., M.M.Tr.", "fraksi": "NasDem", "dapil": "Sumatera Barat I", "provinsi": "Sumatera Barat", "komisi": "VIII", "jabatan": "Anggota"},
    {"nama": "Ir. M. Shadiq Pasadigoe S.H., M.M.", "fraksi": "NasDem", "dapil": "Sumatera Barat I", "provinsi": "Sumatera Barat", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Rahmat Saleh S.Farm.", "fraksi": "PKS", "dapil": "Sumatera Barat I", "provinsi": "Sumatera Barat", "komisi": "II", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Athari Ghauthi Ardi S.H.", "fraksi": "PAN", "dapil": "Sumatera Barat I", "provinsi": "Sumatera Barat", "komisi": "V", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ade Rezki Pratama S.E., M.M.", "fraksi": "Gerindra", "dapil": "Sumatera Barat II", "provinsi": "Sumatera Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "H. Benny Utama S.H., M.M.", "fraksi": "Golkar", "dapil": "Sumatera Barat II", "provinsi": "Sumatera Barat", "komisi": "III", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Cindy Monica Salsabila Setiawan S.M.", "fraksi": "NasDem", "dapil": "Sumatera Barat II", "provinsi": "Sumatera Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Nevi Zuairina", "fraksi": "PKS", "dapil": "Sumatera Barat II", "provinsi": "Sumatera Barat", "komisi": "XII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Arisal Aziz", "fraksi": "PAN", "dapil": "Sumatera Barat II", "provinsi": "Sumatera Barat", "komisi": "XIII", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Ir. H. Mulyadi", "fraksi": "Demokrat", "dapil": "Sumatera Barat II", "provinsi": "Sumatera Barat", "komisi": "XII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Iyeth Bustami", "fraksi": "PKB", "dapil": "Riau I", "provinsi": "Riau", "komisi": "XII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Muhammad Rahul S.H.", "fraksi": "Gerindra", "dapil": "Riau I", "provinsi": "Riau", "komisi": "III", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Dewi Juliani S.H.", "fraksi": "PDI-P", "dapil": "Riau I", "provinsi": "Riau", "komisi": "III", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Syamsuar", "fraksi": "Golkar", "dapil": "", "provinsi": "Riau", "komisi": "", "jabatan": "Anggota"},
    {"nama": "Dr. Hj. Karmila Sari S.Kom, M.M.", "fraksi": "Golkar", "dapil": "", "provinsi": "Riau", "komisi": "X", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Hendry Munief M.B.A.", "fraksi": "PKS", "dapil": "", "provinsi": "Riau", "komisi": "VII", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Achmad M.Si.", "fraksi": "Demokrat", "dapil": "", "provinsi": "Riau", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Abdul Wahid", "fraksi": "PKB", "dapil": "Riau II", "provinsi": "Riau", "komisi": "", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Muhammad Rohid", "fraksi": "Gerindra", "dapil": "Riau II", "provinsi": "Riau", "komisi": "XII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Siti Aisyah", "fraksi": "PDI-P", "dapil": "Riau II", "provinsi": "Riau", "komisi": "XIII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Yulisman S.Si., M.M.", "fraksi": "Golkar", "dapil": "Riau II", "provinsi": "Riau", "komisi": "III", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Syahrul Aidi Maazat Lc., M.A.", "fraksi": "PKS", "dapil": "Riau II", "provinsi": "Riau", "komisi": "V", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Ir. H. Sahidin", "fraksi": "PAN", "dapil": "Riau II", "provinsi": "Riau", "komisi": "II", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Elpisina", "fraksi": "PKB", "dapil": "Jambi", "provinsi": "Jambi", "komisi": "XIII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Rocky Candra", "fraksi": "Gerindra", "dapil": "Jambi", "provinsi": "Jambi", "komisi": "XII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Edi Purwanto M.Si.", "fraksi": "PDI-P", "dapil": "Jambi", "provinsi": "Jambi", "komisi": "V", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Drs. H. Cek Endra", "fraksi": "Golkar", "dapil": "Jambi", "provinsi": "Jambi", "komisi": "XII", "jabatan": "Anggota"},
    {"nama": "H. Hasan Basri Agus", "fraksi": "Golkar", "dapil": "Jambi", "provinsi": "Jambi", "komisi": "VIII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Syarif Fasha S.E., M.E.", "fraksi": "NasDem", "dapil": "Jambi", "provinsi": "Jambi", "komisi": "XII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "H. A. Bakri H. M. S.E.", "fraksi": "PAN", "dapil": "Jambi", "provinsi": "Jambi", "komisi": "V", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "H. Zulfikar Achmad", "fraksi": "Demokrat", "dapil": "Jambi", "provinsi": "Jambi", "komisi": "IX", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "H. S. N. Prana Putra Sohe", "fraksi": "PKB", "dapil": "Sumatera Selatan I", "provinsi": "Sumatera Selatan", "komisi": "XIII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Kartika Sandra Desi S.H., M.M.", "fraksi": "Gerindra", "dapil": "Sumatera Selatan I", "provinsi": "Sumatera Selatan", "komisi": "IV", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Yulian Gunhar S.H., M.H.", "fraksi": "PDI-P", "dapil": "Sumatera Selatan I", "provinsi": "Sumatera Selatan", "komisi": "XII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Yudha Novanza Utama", "fraksi": "Golkar", "dapil": "Sumatera Selatan I", "provinsi": "Sumatera Selatan", "komisi": "I", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Fauzi H. Amro", "fraksi": "NasDem", "dapil": "Sumatera Selatan I", "provinsi": "Sumatera Selatan", "komisi": "XI", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Drs. H. Mohd. Iqbal Romzi", "fraksi": "PKS", "dapil": "Sumatera Selatan I", "provinsi": "Sumatera Selatan", "komisi": "X", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Ir. H. Ishak Mekki M.M.", "fraksi": "Demokrat", "dapil": "Sumatera Selatan I", "provinsi": "Sumatera Selatan", "komisi": "V", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Bertu Merlas S.T.", "fraksi": "PKB", "dapil": "Sumatera Selatan II", "provinsi": "Sumatera Selatan", "komisi": "XI", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ahmad Wazir Noviadi S.Psi., M.Si.", "fraksi": "Gerindra", "dapil": "Sumatera Selatan II", "provinsi": "Sumatera Selatan", "komisi": "II", "jabatan": "Anggota"},
    {"nama": "Ir. Hj. Sri Meliyana", "fraksi": "Gerindra", "dapil": "Sumatera Selatan II", "provinsi": "Sumatera Selatan", "komisi": "IX", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "H. M. Giri Ramanda N. Kiemas S.E., M.M.", "fraksi": "PDI-P", "dapil": "Sumatera Selatan II", "provinsi": "Sumatera Selatan", "komisi": "II", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dewi Yustisiana S.H., M.Kn.", "fraksi": "Golkar", "dapil": "Sumatera Selatan II", "provinsi": "Sumatera Selatan", "komisi": "XII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Irma Suryani S.E., M.M.", "fraksi": "NasDem", "dapil": "Sumatera Selatan II", "provinsi": "Sumatera Selatan", "komisi": "IX", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Askweni S.Pd.", "fraksi": "PKS", "dapil": "Sumatera Selatan II", "provinsi": "Sumatera Selatan", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Iskandar S.E.", "fraksi": "PAN", "dapil": "Sumatera Selatan II", "provinsi": "Sumatera Selatan", "komisi": "VI", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Wahyu Sanjaya S.E., M.M.", "fraksi": "Demokrat", "dapil": "Sumatera Selatan II", "provinsi": "Sumatera Selatan", "komisi": "XI", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Eko Kurnia Ningsih", "fraksi": "PDI-P", "dapil": "Bengkulu", "provinsi": "Bengkulu", "komisi": "IX", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Derta Rohidin", "fraksi": "Golkar", "dapil": "Bengkulu", "provinsi": "Bengkulu", "komisi": "VIII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Erna Sari Dewi S.E.", "fraksi": "NasDem", "dapil": "Bengkulu", "provinsi": "Bengkulu", "komisi": "VII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Dewi Coryati M.Si.", "fraksi": "PAN", "dapil": "Bengkulu", "provinsi": "Bengkulu", "komisi": "X", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Muhammad Kadafi S.H., M.H.", "fraksi": "PKB", "dapil": "Lampung I", "provinsi": "Lampung", "komisi": "X", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ruby Chairani Syiffadia B.A. (Hons), M.Sc.", "fraksi": "Gerindra", "dapil": "Lampung I", "provinsi": "Lampung", "komisi": "X", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Drs. Mukhlis Basri", "fraksi": "PDI-P", "dapil": "Lampung I", "provinsi": "Lampung", "komisi": "V", "jabatan": "Anggota"},
    {"nama": "Sudin S.E.", "fraksi": "PDI-P", "dapil": "Lampung I", "provinsi": "Lampung", "komisi": "III", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Rycko Menoza M.B.A.", "fraksi": "Golkar", "dapil": "Lampung I", "provinsi": "Lampung", "komisi": "VII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Rahmawati Herdian S.H., M.Kn.", "fraksi": "NasDem", "dapil": "Lampung I", "provinsi": "Lampung", "komisi": "IX", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Al Muzzammil Yusuf M.Si.", "fraksi": "PKS", "dapil": "Lampung I", "provinsi": "Lampung", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Putri Zulkifli Hasan", "fraksi": "PAN", "dapil": "Lampung I", "provinsi": "Lampung", "komisi": "XII", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "H. Zulkifli Anwar", "fraksi": "Demokrat", "dapil": "Lampung I", "provinsi": "Lampung", "komisi": "II", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Chusnunia M.Si.", "fraksi": "PKB", "dapil": "Lampung II", "provinsi": "Lampung", "komisi": "VII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ir. Dwita Ria Gunadi", "fraksi": "Gerindra", "dapil": "Lampung II", "provinsi": "Lampung", "komisi": "IV", "jabatan": "Anggota"},
    {"nama": "Dr. Bob Hasan S.H., M.H.", "fraksi": "Gerindra", "dapil": "Lampung II", "provinsi": "Lampung", "komisi": "III", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "drh. I Ketut Suwendra M.M.", "fraksi": "PDI-P", "dapil": "Lampung II", "provinsi": "Lampung", "komisi": "IV", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Ir. Hanan A. Rozak M.S.", "fraksi": "Golkar", "dapil": "Lampung II", "provinsi": "Lampung", "komisi": "IV", "jabatan": "Anggota"},
    {"nama": "H. Aprozi Alam S.E.", "fraksi": "Golkar", "dapil": "Lampung II", "provinsi": "Lampung", "komisi": "VIII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Tamanuri", "fraksi": "NasDem", "dapil": "Lampung II", "provinsi": "Lampung", "komisi": "V", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Ir. H. A. Junaidi Auly M.M.", "fraksi": "PKS", "dapil": "Lampung II", "provinsi": "Lampung", "komisi": "XI", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Irham Jafar Lan Putra S.Hut., M.H.", "fraksi": "PAN", "dapil": "Lampung II", "provinsi": "Lampung", "komisi": "IV", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Marwan Cik Asan", "fraksi": "Demokrat", "dapil": "Lampung II", "provinsi": "Lampung", "komisi": "XI", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Melati S.H.", "fraksi": "Gerindra", "dapil": "Kepulauan Bangka Belitung", "provinsi": "Kepulauan Bangka Belitung", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Ir. Rudianto Tjen", "fraksi": "PDI-P", "dapil": "Kepulauan Bangka Belitung", "provinsi": "Kepulauan Bangka Belitung", "komisi": "I", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Bambang Patijaya S.E., M.M.", "fraksi": "Golkar", "dapil": "Kepulauan Bangka Belitung", "provinsi": "Kepulauan Bangka Belitung", "komisi": "XII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ir. H. M. Endipat Wijaya M.M.", "fraksi": "Gerindra", "dapil": "Kepulauan Riau", "provinsi": "Kepulauan Riau", "komisi": "I", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Mayjen. TNI (Purn.) Sturman Panjaitan S.H.", "fraksi": "PDI-P", "dapil": "Kepulauan Riau", "provinsi": "Kepulauan Riau", "komisi": "IV", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Rizki Faisal", "fraksi": "Golkar", "dapil": "Kepulauan Riau", "provinsi": "Kepulauan Riau", "komisi": "III", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Randi Zulmariadi S.M.", "fraksi": "NasDem", "dapil": "Kepulauan Riau", "provinsi": "Kepulauan Riau", "komisi": "VI", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "H. Hasbiallah Ilyas", "fraksi": "PKB", "dapil": "DKI Jakarta I", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "III", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Habiburokhman S.H., M.H.", "fraksi": "Gerindra", "dapil": "DKI Jakarta I", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "III", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Putra Nababan", "fraksi": "PDI-P", "dapil": "DKI Jakarta I", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "VII", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Mardani Ali Sera M.Eng.", "fraksi": "PKS", "dapil": "DKI Jakarta I", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "II", "jabatan": "Anggota"},
    {"nama": "Dr. Hj. Anis Byarwati", "fraksi": "PKS", "dapil": "DKI Jakarta I", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "XI", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Eko Hendro Purnomo S.Sos.", "fraksi": "PAN", "dapil": "DKI Jakarta I", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "VI", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Ida Fauziyah M.Si.", "fraksi": "PKB", "dapil": "DKI Jakarta II", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "VI", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Himmatul Aliyah S.Sos., M.Si.", "fraksi": "Gerindra", "dapil": "DKI Jakarta II", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "X", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Once Mekel S.H.", "fraksi": "PDI-P", "dapil": "DKI Jakarta II", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "X", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Abraham Sridjaja S.H., M.H., C.L.A.", "fraksi": "Golkar", "dapil": "DKI Jakarta II", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "I", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Kurniasih Mufidayati M.Si.", "fraksi": "PKS", "dapil": "DKI Jakarta II", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "IX", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Surya Utama S.I.P.", "fraksi": "PAN", "dapil": "DKI Jakarta II", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "IX", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Rahayu Saraswati D. Djojohadikusumo", "fraksi": "Gerindra", "dapil": "DKI Jakarta III", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "VII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Charles Honoris", "fraksi": "PDI-P", "dapil": "DKI Jakarta III", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "IX", "jabatan": "Anggota"},
    {"nama": "Prof. Asc. Dr. Darmadi Durianto", "fraksi": "PDI-P", "dapil": "DKI Jakarta III", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "VI", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Erwin Aksa", "fraksi": "Golkar", "dapil": "DKI Jakarta III", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "XI", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "owspan=2|Ahmad Sahroni S.E., M.I.Kom.", "fraksi": "NasDem", "dapil": "DKI Jakarta III", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "III", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Drs. H. Adang Daradjatun", "fraksi": "PKS", "dapil": "DKI Jakarta III", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "III", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Sigit Purnomo S.A.P., S.H.", "fraksi": "PAN", "dapil": "DKI Jakarta III", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "VIII", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Nurwayah S.Pd.", "fraksi": "Demokrat", "dapil": "DKI Jakarta III", "provinsi": "Daerah Khusus Ibukota Jakarta", "komisi": "XII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Habib Syarief Muhammad", "fraksi": "PKB", "dapil": "Jawa Barat I", "provinsi": "Jawa Barat", "komisi": "X", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Melly Goeslaw", "fraksi": "Gerindra", "dapil": "Jawa Barat I", "provinsi": "Jawa Barat", "komisi": "X", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Junico B. P. Siahaan S.E.", "fraksi": "PDI-P", "dapil": "Jawa Barat I", "provinsi": "Jawa Barat", "komisi": "I", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Atalia Praratya S.I.P., M.I.Kom.", "fraksi": "Golkar", "dapil": "Jawa Barat I", "provinsi": "Jawa Barat", "komisi": "VIII", "jabatan": "Anggota"},
    {"nama": "Nurul Arifin M.Si.", "fraksi": "Golkar", "dapil": "Jawa Barat I", "provinsi": "Jawa Barat", "komisi": "I", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Ledia Hanifa A. S.Si., M.Psi.T.", "fraksi": "PKS", "dapil": "Jawa Barat I", "provinsi": "Jawa Barat", "komisi": "X", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "H. Fathi", "fraksi": "Demokrat", "dapil": "Jawa Barat I", "provinsi": "Jawa Barat", "komisi": "XI", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "H. Cucun Ahmad Syamsurijal", "fraksi": "PKB", "dapil": "Jawa Barat II", "provinsi": "Jawa Barat", "komisi": "III", "jabatan": "Wakil Ketua DPR RI"},
    {"nama": "Asep Romy Romaya", "fraksi": "PKB", "dapil": "Jawa Barat II", "provinsi": "Jawa Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Rachel Maryam Sayidina", "fraksi": "Gerindra", "dapil": "Jawa Barat II", "provinsi": "Jawa Barat", "komisi": "I", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Denny Cagur S.Pd.", "fraksi": "PDI-P", "dapil": "Jawa Barat II", "provinsi": "Jawa Barat", "komisi": "X", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. TB. Ace Hasan Syadzily M.Si.", "fraksi": "Golkar", "dapil": "Jawa Barat II", "provinsi": "Jawa Barat", "komisi": "XIII", "jabatan": "Anggota"},
    {"nama": "Dr. H. Dadang M. Naser S.H., M.I.Pol.", "fraksi": "Golkar", "dapil": "Jawa Barat II", "provinsi": "Jawa Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Rajiv", "fraksi": "NasDem", "dapil": "Jawa Barat II", "provinsi": "Jawa Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Ahmad Heryawan Lc., M.Si.", "fraksi": "PKS", "dapil": "Jawa Barat II", "provinsi": "Jawa Barat", "komisi": "I", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Ahmad Najib Qodratullah S.E., M.H.", "fraksi": "PAN", "dapil": "Jawa Barat II", "provinsi": "Jawa Barat", "komisi": "XI", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Dede Yusuf Macan Effendi S.T., M.I.Pol.", "fraksi": "Demokrat", "dapil": "Jawa Barat II", "provinsi": "Jawa Barat", "komisi": "II", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Neng Eem Marhamah Zulfa Hiz S.Th.I., M.M.", "fraksi": "PKB", "dapil": "Jawa Barat III", "provinsi": "Jawa Barat", "komisi": "XI", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Kamrussamad", "fraksi": "Gerindra", "dapil": "Jawa Barat III", "provinsi": "Jawa Barat", "komisi": "XI", "jabatan": "Anggota"},
    {"nama": "Dr. Ir. Hj. Endang Setyawati Thohari DESS., M.Sc.", "fraksi": "Gerindra", "dapil": "Jawa Barat III", "provinsi": "Jawa Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "H. Muhamad Abdul Aziz Sefudin", "fraksi": "PDI-P", "dapil": "Jawa Barat III", "provinsi": "Jawa Barat", "komisi": "VIII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Budhy Setiawan", "fraksi": "Golkar", "dapil": "Jawa Barat III", "provinsi": "Jawa Barat", "komisi": "", "jabatan": "Anggota"},
    {"nama": "Ilham Permana", "fraksi": "Golkar", "dapil": "Jawa Barat III", "provinsi": "Jawa Barat", "komisi": "VII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Ananda Tohpati N. R.", "fraksi": "NasDem", "dapil": "Jawa Barat III", "provinsi": "Jawa Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Ecky Awal Mucharam", "fraksi": "PKS", "dapil": "Jawa Barat III", "provinsi": "Jawa Barat", "komisi": "XI", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Zainul Munasichin", "fraksi": "PKB", "dapil": "Jawa Barat IV", "provinsi": "Jawa Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Heri Gunawan", "fraksi": "Gerindra", "dapil": "Jawa Barat IV", "provinsi": "Jawa Barat", "komisi": "II", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Dewi Asmara S.H., M.H.", "fraksi": "Golkar", "dapil": "Jawa Barat IV", "provinsi": "Jawa Barat", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "drh. Slamet", "fraksi": "PKS", "dapil": "Jawa Barat IV", "provinsi": "Jawa Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Desy Ratnasari S.Psi., M.Si., M.Psi.", "fraksi": "PAN", "dapil": "Jawa Barat IV", "provinsi": "Jawa Barat", "komisi": "I", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Iman Adinugraha S.E., Akt.", "fraksi": "Demokrat", "dapil": "Jawa Barat IV", "provinsi": "Jawa Barat", "komisi": "VII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Tommy Kurniawan", "fraksi": "PKB", "dapil": "Jawa Barat V", "provinsi": "Jawa Barat", "komisi": "XI", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Fadli Zon S.S., M.Sc.", "fraksi": "Gerindra", "dapil": "Jawa Barat V", "provinsi": "Jawa Barat", "komisi": "I", "jabatan": "Anggota"},
    {"nama": "Hj. Marlyn Maisarah", "fraksi": "Gerindra", "dapil": "Jawa Barat V", "provinsi": "Jawa Barat", "komisi": "V", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Adian Y. Y. Napitupulu S.H.", "fraksi": "PDI-P", "dapil": "Jawa Barat V", "provinsi": "Jawa Barat", "komisi": "V", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Ravindra Airlangga M.S.", "fraksi": "Golkar", "dapil": "Jawa Barat V", "provinsi": "Jawa Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Asep Wahyuwijaya", "fraksi": "NasDem", "dapil": "Jawa Barat V", "provinsi": "Jawa Barat", "komisi": "VI", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "drh. H. Achmad Ru'yat M.Si.", "fraksi": "PKS", "dapil": "Jawa Barat V", "provinsi": "Jawa Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Primus Yustisio S.E., M.A.P.", "fraksi": "PAN", "dapil": "Jawa Barat V", "provinsi": "Jawa Barat", "komisi": "XI", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "H. Anton Sukartono Suratto M.Si.", "fraksi": "Demokrat", "dapil": "Jawa Barat V", "provinsi": "Jawa Barat", "komisi": "I", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "H. Sudjatmiko S.T.", "fraksi": "PKB", "dapil": "Jawa Barat VI", "provinsi": "Jawa Barat", "komisi": "V", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ir. H. Nuroji", "fraksi": "Gerindra", "dapil": "Jawa Barat VI", "provinsi": "Jawa Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Sukur H. Nababan S.T.", "fraksi": "PDI-P", "dapil": "Jawa Barat VI", "provinsi": "Jawa Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Ranny Fahd Arafiq", "fraksi": "Golkar", "dapil": "Jawa Barat VI", "provinsi": "Jawa Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Mahfudz Abdurrahman S.Sos.", "fraksi": "PKS", "dapil": "Jawa Barat VI", "provinsi": "Jawa Barat", "komisi": "X", "jabatan": "Anggota"},
    {"nama": "H. Muhammad Kholid S.E., M.Si.", "fraksi": "PKS", "dapil": "Jawa Barat VI", "provinsi": "Jawa Barat", "komisi": "XI", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Syaiful Huda", "fraksi": "PKB", "dapil": "Jawa Barat VII", "provinsi": "Jawa Barat", "komisi": "V", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "H. Dedi Mulyadi S.H., M.M.", "fraksi": "Gerindra", "dapil": "Jawa Barat VII", "provinsi": "Jawa Barat", "komisi": "", "jabatan": "Anggota"},
    {"nama": "drg. Hj. Putih Sari M.Dsc.", "fraksi": "Gerindra", "dapil": "Jawa Barat VII", "provinsi": "Jawa Barat", "komisi": "IX", "jabatan": "Anggota"},
    {"nama": "Obon Tabroni", "fraksi": "Gerindra", "dapil": "Jawa Barat VII", "provinsi": "Jawa Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Rieke Diah Pitaloka", "fraksi": "PDI-P", "dapil": "Jawa Barat VII", "provinsi": "Jawa Barat", "komisi": "VI", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Puteri Komarudin", "fraksi": "Golkar", "dapil": "Jawa Barat VII", "provinsi": "Jawa Barat", "komisi": "XI", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Saan Mustopa", "fraksi": "NasDem", "dapil": "Jawa Barat VII", "provinsi": "Jawa Barat", "komisi": "II", "jabatan": "Wakil Ketua DPR RI"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Ahmad Syaikhu", "fraksi": "PKS", "dapil": "", "provinsi": "Jawa Barat", "komisi": "", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Verrell Bramasta", "fraksi": "PAN", "dapil": "", "provinsi": "Jawa Barat", "komisi": "X", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "dr. Hj. Cellica Nurrachadiana M.H.Kes", "fraksi": "Demokrat", "dapil": "", "provinsi": "Jawa Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "H. Dedi Wahidi", "fraksi": "PKB", "dapil": "Jawa Barat VIII", "provinsi": "Jawa Barat", "komisi": "X", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Kardaya Warnika", "fraksi": "Gerindra", "dapil": "Jawa Barat VIII", "provinsi": "Jawa Barat", "komisi": "VII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Prof. Dr. Ir. H. Rokhmin Dahuri M.S.", "fraksi": "PDI-P", "dapil": "Jawa Barat VIII", "provinsi": "Jawa Barat", "komisi": "IV", "jabatan": "Anggota"},
    {"nama": "Hj. Selly Andriany Gantina A.Md., S.T.", "fraksi": "PDI-P", "dapil": "Jawa Barat VIII", "provinsi": "Jawa Barat", "komisi": "VIII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "H. Daniel Mutaqien Syafiuddin S.T.", "fraksi": "Golkar", "dapil": "Jawa Barat VIII", "provinsi": "Jawa Barat", "komisi": "V", "jabatan": "Anggota"},
    {"nama": "Dave Akbarshah Firkarno M.E.", "fraksi": "Golkar", "dapil": "Jawa Barat VIII", "provinsi": "Jawa Barat", "komisi": "I", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Satori S.Pd.I., M.M.", "fraksi": "NasDem", "dapil": "Jawa Barat VIII", "provinsi": "Jawa Barat", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Netty Prasetiyani M.Si.", "fraksi": "PKS", "dapil": "Jawa Barat VIII", "provinsi": "Jawa Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Ir. H. E. Herman Khaeron M.Si.", "fraksi": "Demokrat", "dapil": "Jawa Barat VIII", "provinsi": "Jawa Barat", "komisi": "VI", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "K. H. Maman Imanul Haq M.M.", "fraksi": "PKB", "dapil": "Jawa Barat IX", "provinsi": "Jawa Barat", "komisi": "VIII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Jefry Romdonny S.E., S.Sos., M.Si., M.M.", "fraksi": "Gerindra", "dapil": "Jawa Barat IX", "provinsi": "Jawa Barat", "komisi": "XI", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Elita Budiati S.K.M., M.Si.", "fraksi": "Golkar", "dapil": "Jawa Barat IX", "provinsi": "Jawa Barat", "komisi": "I", "jabatan": "Anggota"},
    {"nama": "Galih Dimuntur Kartasasmita", "fraksi": "Golkar", "dapil": "Jawa Barat IX", "provinsi": "Jawa Barat", "komisi": "XI", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Ujang Bey S.I.P., M.I.P.", "fraksi": "NasDem", "dapil": "Jawa Barat IX", "provinsi": "Jawa Barat", "komisi": "II", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Ir. H. Ateng Sutisna", "fraksi": "PKS", "dapil": "Jawa Barat IX", "provinsi": "Jawa Barat", "komisi": "II", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Farah Puteri Nahlia B.A., M.Sc.", "fraksi": "PAN", "dapil": "Jawa Barat IX", "provinsi": "Jawa Barat", "komisi": "I", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Rina Sa'adah Lc., M.Si.", "fraksi": "PKB", "dapil": "Jawa Barat X", "provinsi": "Jawa Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "H. Rokhmat Ardiyan M.M.", "fraksi": "Gerindra", "dapil": "Jawa Barat X", "provinsi": "Jawa Barat", "komisi": "XII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Ida Nurlaela Wiradinata", "fraksi": "PDI-P", "dapil": "Jawa Barat X", "provinsi": "Jawa Barat", "komisi": "VI", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Tr. Agun Gunandjar S. Bc.I.P., M.Si.", "fraksi": "Golkar", "dapil": "Jawa Barat X", "provinsi": "Jawa Barat", "komisi": "XIII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Shohibul Imam CA., CPA.", "fraksi": "NasDem", "dapil": "Jawa Barat X", "provinsi": "Jawa Barat", "komisi": "XI", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. K. H. Surahman Hidayat Lc., M.A.", "fraksi": "PKS", "dapil": "Jawa Barat X", "provinsi": "Jawa Barat", "komisi": "III", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Ir. H. Herry Dermawan", "fraksi": "PAN", "dapil": "Jawa Barat X", "provinsi": "Jawa Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Imas Aan Ubudiah S.Pd.I.", "fraksi": "PKB", "dapil": "Jawa Barat XI", "provinsi": "Jawa Barat", "komisi": "VI", "jabatan": "Anggota"},
    {"nama": "H. Oleh Soleh S.H.", "fraksi": "PKB", "dapil": "Jawa Barat XI", "provinsi": "Jawa Barat", "komisi": "I", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Muhammad Husein Fadlulloh B.Bus., M.M., M.B.A.", "fraksi": "Gerindra", "dapil": "Jawa Barat XI", "provinsi": "Jawa Barat", "komisi": "VI", "jabatan": "Anggota"},
    {"nama": "Mulan Jameela S.S.", "fraksi": "Gerindra", "dapil": "Jawa Barat XI", "provinsi": "Jawa Barat", "komisi": "VI", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Dony Maryadi Oekon S.T.", "fraksi": "PDI-P", "dapil": "Jawa Barat XI", "provinsi": "Jawa Barat", "komisi": "XII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Ade Ginanjar S.Sos.", "fraksi": "Golkar", "dapil": "Jawa Barat XI", "provinsi": "Jawa Barat", "komisi": "II", "jabatan": "Anggota"},
    {"nama": "Ferdiansyah S.E., M.M.", "fraksi": "Golkar", "dapil": "Jawa Barat XI", "provinsi": "Jawa Barat", "komisi": "X", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Lola Nelria Oktavia", "fraksi": "NasDem", "dapil": "Jawa Barat XI", "provinsi": "Jawa Barat", "komisi": "III", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Mohamad Sohibul Iman M.Sc., Ph.D.", "fraksi": "PKS", "dapil": "Jawa Barat XI", "provinsi": "Jawa Barat", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Muhammad Hoerudin Amin S.Ag., M.H.", "fraksi": "PAN", "dapil": "Jawa Barat XI", "provinsi": "Jawa Barat", "komisi": "X", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "H. Sugiono B.Sc., M.Sc.", "fraksi": "Gerindra", "dapil": "Jawa Tengah I", "provinsi": "Jawa Tengah", "komisi": "I", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Mochamad Herviano Widyatama S.Sos., M.M.", "fraksi": "PDI-P", "dapil": "Jawa Tengah I", "provinsi": "Jawa Tengah", "komisi": "V", "jabatan": "Anggota"},
    {"nama": "Samuel J. D. Wattimena", "fraksi": "PDI-P", "dapil": "Jawa Tengah I", "provinsi": "Jawa Tengah", "komisi": "VII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Firnando Hadityo Ganinduto B.A.", "fraksi": "Golkar", "dapil": "Jawa Tengah I", "provinsi": "Jawa Tengah", "komisi": "VI", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Drs. Fadholi", "fraksi": "NasDem", "dapil": "Jawa Tengah I", "provinsi": "Jawa Tengah", "komisi": "V", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Muhammad Haris S.S., M.Si.", "fraksi": "PKS", "dapil": "Jawa Tengah I", "provinsi": "Jawa Tengah", "komisi": "XII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "H. A. S. Sukawijaya alias Yoyok Sukawi S.E., M.M.", "fraksi": "PAN", "dapil": "Jawa Tengah I", "provinsi": "Jawa Tengah", "komisi": "", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Fathan S.Ag., M.A.P.", "fraksi": "PKB", "dapil": "Jawa Tengah II", "provinsi": "Jawa Tengah", "komisi": "", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Abdul Wachid", "fraksi": "Gerindra", "dapil": "Jawa Tengah II", "provinsi": "Jawa Tengah", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Musthofa S.E., M.M.", "fraksi": "PDI-P", "dapil": "Jawa Tengah II", "provinsi": "Jawa Tengah", "komisi": "XI", "jabatan": "Anggota"},
    {"nama": "Gilang Dhielafararez S.H., LL.M.", "fraksi": "PDI-P", "dapil": "Jawa Tengah II", "provinsi": "Jawa Tengah", "komisi": "III", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Nusron Wahid S.S., M.Si.", "fraksi": "Golkar", "dapil": "Jawa Tengah II", "provinsi": "Jawa Tengah", "komisi": "VII", "jabatan": "Anggota"},
    {"nama": "Jamaludin Malik", "fraksi": "Golkar", "dapil": "Jawa Tengah II", "provinsi": "Jawa Tengah", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Marwan Jafar", "fraksi": "PKB", "dapil": "Jawa Tengah III", "provinsi": "Jawa Tengah", "komisi": "I", "jabatan": "Anggota"},
    {"nama": "Eva Monalisa", "fraksi": "PKB", "dapil": "Jawa Tengah III", "provinsi": "Jawa Tengah", "komisi": "VII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Sudewo S.T., M.T.", "fraksi": "Gerindra", "dapil": "Jawa Tengah III", "provinsi": "Jawa Tengah", "komisi": "", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Haryanto S.H., M.M., M.Si.", "fraksi": "PDI-P", "dapil": "Jawa Tengah III", "provinsi": "Jawa Tengah", "komisi": "V", "jabatan": "Anggota"},
    {"nama": "Dr. Evita Nursanty S.H., M.Sc.", "fraksi": "PDI-P", "dapil": "Jawa Tengah III", "provinsi": "Jawa Tengah", "komisi": "VII", "jabatan": "Anggota"},
    {"nama": "Dr. H. Edy Wuryanto S.Kp., M.Kep.", "fraksi": "PDI-P", "dapil": "Jawa Tengah III", "provinsi": "Jawa Tengah", "komisi": "IX", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Firman Soebagyo", "fraksi": "Golkar", "dapil": "Jawa Tengah III", "provinsi": "Jawa Tengah", "komisi": "IV", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Sri Wulan S.E., M.M.", "fraksi": "NasDem", "dapil": "Jawa Tengah III", "provinsi": "Jawa Tengah", "komisi": "VIII", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Harmusa Oktaviani S.E., M.H.", "fraksi": "Demokrat", "dapil": "Jawa Tengah III", "provinsi": "Jawa Tengah", "komisi": "V", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ir. Sriyanto Saputro M.M.", "fraksi": "Gerindra", "dapil": "Jawa Tengah IV", "provinsi": "Jawa Tengah", "komisi": "V", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Dolfie O. F. P. S.T.", "fraksi": "PDI-P", "dapil": "Jawa Tengah IV", "provinsi": "Jawa Tengah", "komisi": "XI", "jabatan": "Anggota"},
    {"nama": "Diah Pikatan O. Putri Haprani", "fraksi": "PDI-P", "dapil": "Jawa Tengah IV", "provinsi": "Jawa Tengah", "komisi": "XI", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Drs. Juliyatmono M.M., M.H.", "fraksi": "Golkar", "dapil": "Jawa Tengah IV", "provinsi": "Jawa Tengah", "komisi": "X", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Drs. Hamid Noor Yasin M.M.", "fraksi": "PKS", "dapil": "Jawa Tengah IV", "provinsi": "Jawa Tengah", "komisi": "XIII", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Rinto Subekti S.E., M.M.", "fraksi": "Demokrat", "dapil": "Jawa Tengah IV", "provinsi": "Jawa Tengah", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "H. Mohamad Toha M.Si.", "fraksi": "PKB", "dapil": "Jawa Tengah V", "provinsi": "Jawa Tengah", "komisi": "II", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Adik Sasongko", "fraksi": "Gerindra", "dapil": "Jawa Tengah V", "provinsi": "Jawa Tengah", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Puan Maharani", "fraksi": "PDI-P", "dapil": "Jawa Tengah V", "provinsi": "Jawa Tengah", "komisi": "I", "jabatan": "Ketua DPR RI"},
    {"nama": "Aria Bima", "fraksi": "PDI-P", "dapil": "Jawa Tengah V", "provinsi": "Jawa Tengah", "komisi": "II", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "H. Singgih Januratmoko S.K.H., M.M.", "fraksi": "Golkar", "dapil": "Jawa Tengah V", "provinsi": "Jawa Tengah", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Abdul Kharis Almasyhari S.E., M.Si.", "fraksi": "PKS", "dapil": "Jawa Tengah V", "provinsi": "Jawa Tengah", "komisi": "IV", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Muhammad Hatta", "fraksi": "PAN", "dapil": "Jawa Tengah V", "provinsi": "Jawa Tengah", "komisi": "VII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Abdullah", "fraksi": "PKB", "dapil": "Jawa Tengah VI", "provinsi": "Jawa Tengah", "komisi": "III", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Prasetyo Hadi", "fraksi": "Gerindra", "dapil": "Jawa Tengah VI", "provinsi": "Jawa Tengah", "komisi": "II", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Vita Ervina S.E., M.B.A.", "fraksi": "PDI-P", "dapil": "Jawa Tengah VI", "provinsi": "Jawa Tengah", "komisi": "XIII", "jabatan": "Anggota"},
    {"nama": "Sofwan Dedy Ardyanto", "fraksi": "PDI-P", "dapil": "Jawa Tengah VI", "provinsi": "Jawa Tengah", "komisi": "V", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Ir. Panggah Susanto M.M.", "fraksi": "Golkar", "dapil": "Jawa Tengah VI", "provinsi": "Jawa Tengah", "komisi": "IV", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Nafa Urbach", "fraksi": "NasDem", "dapil": "Jawa Tengah VI", "provinsi": "Jawa Tengah", "komisi": "IX", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Bramantyo Suwondo M.", "fraksi": "Demokrat", "dapil": "Jawa Tengah VI", "provinsi": "Jawa Tengah", "komisi": "X", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Drs. H. Taufiq R. Abdullah", "fraksi": "PKB", "dapil": "Jawa Tengah VII", "provinsi": "Jawa Tengah", "komisi": "I", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ir. KRT. H. Darori Wonodipuro M.M., IPU.", "fraksi": "Gerindra", "dapil": "Jawa Tengah VII", "provinsi": "Jawa Tengah", "komisi": "IV", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Drs. Utut Adianto", "fraksi": "PDI-P", "dapil": "Jawa Tengah VII", "provinsi": "Jawa Tengah", "komisi": "I", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Bambang Soesatyo S.E.", "fraksi": "Golkar", "dapil": "Jawa Tengah VII", "provinsi": "Jawa Tengah", "komisi": "III", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Amelia Anggraini", "fraksi": "NasDem", "dapil": "Jawa Tengah VII", "provinsi": "Jawa Tengah", "komisi": "I", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Rofik Hananto S.E.", "fraksi": "PKS", "dapil": "Jawa Tengah VII", "provinsi": "Jawa Tengah", "komisi": "VII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Aqib Ardiansyah M.Si.", "fraksi": "PAN", "dapil": "Jawa Tengah VII", "provinsi": "Jawa Tengah", "komisi": "XII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Siti Mukaromah S.Ag., M.A.P.", "fraksi": "PKB", "dapil": "Jawa Tengah VIII", "provinsi": "Jawa Tengah", "komisi": "VII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Novita Wijayanti S.M., M.M.", "fraksi": "Gerindra", "dapil": "Jawa Tengah VIII", "provinsi": "Jawa Tengah", "komisi": "V", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Kaisar Kiasa Kasih Said Putra", "fraksi": "PDI-P", "dapil": "Jawa Tengah VIII", "provinsi": "Jawa Tengah", "komisi": "XI", "jabatan": "Anggota"},
    {"nama": "Adisatrya Suryo Sulisto", "fraksi": "PDI-P", "dapil": "Jawa Tengah VIII", "provinsi": "Jawa Tengah", "komisi": "VI", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Teti Rohatiningsih S.Sos.", "fraksi": "Golkar", "dapil": "Jawa Tengah VIII", "provinsi": "Jawa Tengah", "komisi": "IX", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Sugeng Suparwoto", "fraksi": "NasDem", "dapil": "Jawa Tengah VIII", "provinsi": "Jawa Tengah", "komisi": "XII", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Yanuar Arif Wibowo S.H.", "fraksi": "PKS", "dapil": "Jawa Tengah VIII", "provinsi": "Jawa Tengah", "komisi": "V", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "H. Wastam S.E.", "fraksi": "Demokrat", "dapil": "Jawa Tengah VIII", "provinsi": "Jawa Tengah", "komisi": "V", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Eka Widodo", "fraksi": "PKB", "dapil": "Jawa Tengah IX", "provinsi": "Jawa Tengah", "komisi": "II", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Mohamad Hekal B.Sc., M.B.A.", "fraksi": "Gerindra", "dapil": "Jawa Tengah IX", "provinsi": "Jawa Tengah", "komisi": "XI", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Shanty Alda Nathalia S.H.", "fraksi": "PDI-P", "dapil": "Jawa Tengah IX", "provinsi": "Jawa Tengah", "komisi": "XII", "jabatan": "Anggota"},
    {"nama": "Dr. Harris Turino S.T., S.H., M.Si., M.M.", "fraksi": "PDI-P", "dapil": "Jawa Tengah IX", "provinsi": "Jawa Tengah", "komisi": "XI", "jabatan": "Anggota"},
    {"nama": "Hj. Shintya Sandra Kusuma S.Hub.Int., M.A.B.", "fraksi": "PDI-P", "dapil": "Jawa Tengah IX", "provinsi": "Jawa Tengah", "komisi": "II", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Abdul Fikri Faqih M.M.", "fraksi": "PKS", "dapil": "Jawa Tengah IX", "provinsi": "Jawa Tengah", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Wahyudin Noor Aly alias Goyud", "fraksi": "PAN", "dapil": "Jawa Tengah IX", "provinsi": "Jawa Tengah", "komisi": "II", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "M. Hanif Dhakiri", "fraksi": "PKB", "dapil": "Jawa Tengah X", "provinsi": "Jawa Tengah", "komisi": "XI", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Ramson Siagian", "fraksi": "Gerindra", "dapil": "Jawa Tengah X", "provinsi": "Jawa Tengah", "komisi": "XII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Dede Indra Permana Soediro S.H.", "fraksi": "PDI-P", "dapil": "Jawa Tengah X", "provinsi": "Jawa Tengah", "komisi": "III", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Ashraff Abu", "fraksi": "Golkar", "dapil": "Jawa Tengah X", "provinsi": "Jawa Tengah", "komisi": "IX", "jabatan": "Anggota"},
    {"nama": "Doni Akbar S.E., M.M.", "fraksi": "Golkar", "dapil": "Jawa Tengah X", "provinsi": "Jawa Tengah", "komisi": "VI", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Yoyok Riyo Sudibyo", "fraksi": "NasDem", "dapil": "Jawa Tengah X", "provinsi": "Jawa Tengah", "komisi": "I", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Rizal Bawazier", "fraksi": "PKS", "dapil": "Jawa Tengah X", "provinsi": "Jawa Tengah", "komisi": "VI", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Kaisar Abu Hanifah", "fraksi": "PKB", "dapil": "Daerah Istimewa Yogyakarta", "provinsi": "Daerah Istimewa Yogyakarta", "komisi": "VII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Siti Hediati Soeharto S.E.", "fraksi": "Gerindra", "dapil": "Daerah Istimewa Yogyakarta", "provinsi": "Daerah Istimewa Yogyakarta", "komisi": "IV", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "M. Y. Esti Wijayati", "fraksi": "PDI-P", "dapil": "Daerah Istimewa Yogyakarta", "provinsi": "Daerah Istimewa Yogyakarta", "komisi": "X", "jabatan": "Anggota"},
    {"nama": "G. M. Totok Hedi Santosa", "fraksi": "PDI-P", "dapil": "Daerah Istimewa Yogyakarta", "provinsi": "Daerah Istimewa Yogyakarta", "komisi": "VI", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Drs. Gandung Pardiman M.M.", "fraksi": "Golkar", "dapil": "Daerah Istimewa Yogyakarta", "provinsi": "Daerah Istimewa Yogyakarta", "komisi": "XII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "H. Subardi S.H., M.H.", "fraksi": "NasDem", "dapil": "Daerah Istimewa Yogyakarta", "provinsi": "Daerah Istimewa Yogyakarta", "komisi": "VI", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Sukamta", "fraksi": "PKS", "dapil": "Daerah Istimewa Yogyakarta", "provinsi": "Daerah Istimewa Yogyakarta", "komisi": "I", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Totok Daryanto S.E.", "fraksi": "PAN", "dapil": "Daerah Istimewa Yogyakarta", "provinsi": "Daerah Istimewa Yogyakarta", "komisi": "XII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Arzeti Bilbina Setyawan S.E., M.AP.", "fraksi": "PKB", "dapil": "Jawa Timur I", "provinsi": "Jawa Timur", "komisi": "IX", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ir. H. Bambang Haryo Soekartono", "fraksi": "Gerindra", "dapil": "Jawa Timur I", "provinsi": "Jawa Timur", "komisi": "VII", "jabatan": "Anggota"},
    {"nama": "Dhani Ahmad Prasetyo S.H.", "fraksi": "Gerindra", "dapil": "Jawa Timur I", "provinsi": "Jawa Timur", "komisi": "X", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Puti Guntur Soekarno S.I.P.", "fraksi": "PDI-P", "dapil": "Jawa Timur I", "provinsi": "Jawa Timur", "komisi": "X", "jabatan": "Anggota"},
    {"nama": "Indah Kurnia S.E., M.M.", "fraksi": "PDI-P", "dapil": "Jawa Timur I", "provinsi": "Jawa Timur", "komisi": "IX", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Ir. H. Adies Kadir S.H., M.Hum.", "fraksi": "Golkar", "dapil": "Jawa Timur I", "provinsi": "Jawa Timur", "komisi": "III", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Lita Machfud Arifin", "fraksi": "NasDem", "dapil": "Jawa Timur I", "provinsi": "Jawa Timur", "komisi": "X", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Reni Astuti S.Si., M.PSDM.", "fraksi": "PKS", "dapil": "Jawa Timur I", "provinsi": "Jawa Timur", "komisi": "V", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Arizal Tom Liwafa S.T., M.M.", "fraksi": "PAN", "dapil": "Jawa Timur I", "provinsi": "Jawa Timur", "komisi": "VII", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Dra. Lucy Kurniasari", "fraksi": "Demokrat", "dapil": "Jawa Timur I", "provinsi": "Jawa Timur", "komisi": "IX", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "H. Faisol Riza S.S., M.A.", "fraksi": "PKB", "dapil": "Jawa Timur II", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},
    {"nama": "Dr. H. Mohammad Irsyad Yusuf S.E., M.M.A.", "fraksi": "PKB", "dapil": "Jawa Timur II", "provinsi": "Jawa Timur", "komisi": "", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Anwar Sadad M.Ag.", "fraksi": "Gerindra", "dapil": "Jawa Timur II", "provinsi": "Jawa Timur", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "dr. H. Mufti A.N. Anam M.I.Kom.", "fraksi": "PDI-P", "dapil": "Jawa Timur II", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Mukhamad Misbakhun S.E., M.H.", "fraksi": "Golkar", "dapil": "Jawa Timur II", "provinsi": "Jawa Timur", "komisi": "XI", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Syaiful Nuri", "fraksi": "PAN", "dapil": "Jawa Timur II", "provinsi": "Jawa Timur", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Nihayatul Wafiroh S.Ag., M.A.", "fraksi": "PKB", "dapil": "Jawa Timur III", "provinsi": "Jawa Timur", "komisi": "IX", "jabatan": "Anggota"},
    {"nama": "Ir. H. M. Nasim Khan", "fraksi": "PKB", "dapil": "Jawa Timur III", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ir. H. Sumail Abdullah M.T.", "fraksi": "Gerindra", "dapil": "Jawa Timur III", "provinsi": "Jawa Timur", "komisi": "I", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Sonny Tri Danaparamita S.H., M.H.", "fraksi": "PDI-P", "dapil": "Jawa Timur III", "provinsi": "Jawa Timur", "komisi": "IV", "jabatan": "Anggota"},
    {"nama": "Ina Ammania", "fraksi": "PDI-P", "dapil": "Jawa Timur III", "provinsi": "Jawa Timur", "komisi": "VIII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Zulfikar Arse Sadikin S.I.P., M.Si.", "fraksi": "Golkar", "dapil": "Jawa Timur III", "provinsi": "Jawa Timur", "komisi": "II", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Dina Lorenza Audria S.I.P., M.A.P.", "fraksi": "Demokrat", "dapil": "Jawa Timur III", "provinsi": "Jawa Timur", "komisi": "VII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "H. Rivqy Abdul Halim S.E.", "fraksi": "PKB", "dapil": "Jawa Timur IV", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},
    {"nama": "H. Ach. Ghufron Sirodj S.Th.I.", "fraksi": "PKB", "dapil": "Jawa Timur IV", "provinsi": "Jawa Timur", "komisi": "", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Bambang Haryadi S.E.", "fraksi": "Gerindra", "dapil": "Jawa Timur IV", "provinsi": "Jawa Timur", "komisi": "XII", "jabatan": "Anggota"},
    {"nama": "Kawendra Lukistian S.E., M.Sn.", "fraksi": "Gerindra", "dapil": "Jawa Timur IV", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Arif Wibowo", "fraksi": "PDI-P", "dapil": "Jawa Timur IV", "provinsi": "Jawa Timur", "komisi": "II", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "H. Muhamad Nur Purnamasidi S.Sos.", "fraksi": "Golkar", "dapil": "Jawa Timur IV", "provinsi": "Jawa Timur", "komisi": "X", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "H. Charles Meikyansah S.Sos., M.I.Kom.", "fraksi": "NasDem", "dapil": "Jawa Timur IV", "provinsi": "Jawa Timur", "komisi": "XI", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Amin Ak., M.M.", "fraksi": "PKS", "dapil": "Jawa Timur IV", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Hassanudin Wahid S.Ag., M.Hum.", "fraksi": "PKB", "dapil": "Jawa Timur V", "provinsi": "Jawa Timur", "komisi": "XI", "jabatan": "Anggota"},
    {"nama": "H. Ali Ahmad S.H.", "fraksi": "PKB", "dapil": "Jawa Timur V", "provinsi": "Jawa Timur", "komisi": "II", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Moreno Soeprapto S.Sos.", "fraksi": "Gerindra", "dapil": "Jawa Timur V", "provinsi": "Jawa Timur", "komisi": "XII", "jabatan": "Anggota"},
    {"nama": "H. Ma'ruf Mubarok S.H.", "fraksi": "Gerindra", "dapil": "Jawa Timur V", "provinsi": "Jawa Timur", "komisi": "VII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Ahmad Basarah S.H., M.H.", "fraksi": "PDI-P", "dapil": "Jawa Timur V", "provinsi": "Jawa Timur", "komisi": "XIII", "jabatan": "Anggota"},
    {"nama": "Ir. Andreas Eddy Susetyo M.M.", "fraksi": "PDI-P", "dapil": "Jawa Timur V", "provinsi": "Jawa Timur", "komisi": "XI", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Ahmad Irawan", "fraksi": "Golkar", "dapil": "Jawa Timur V", "provinsi": "Jawa Timur", "komisi": "II", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "dr. Gamal M.Biomed.", "fraksi": "PKS", "dapil": "Jawa Timur V", "provinsi": "Jawa Timur", "komisi": "X", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Anggia Erma Rini M.K.M.", "fraksi": "PKB", "dapil": "Jawa Timur VI", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},
    {"nama": "H. An'im Falachuddin", "fraksi": "PKB", "dapil": "Jawa Timur VI", "provinsi": "Jawa Timur", "komisi": "VIII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ir. Endro Hermono M.B.A.", "fraksi": "Gerindra", "dapil": "Jawa Timur VI", "provinsi": "Jawa Timur", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Pulung Agustanto", "fraksi": "PDI-P", "dapil": "Jawa Timur VI", "provinsi": "Jawa Timur", "komisi": "III", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "M. Sarmuji S.E., M.S.", "fraksi": "Golkar", "dapil": "Jawa Timur VI", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},
    {"nama": "Dr. Ir. Heru Tjahjono M.M.", "fraksi": "Golkar", "dapil": "Jawa Timur VI", "provinsi": "Jawa Timur", "komisi": "IX", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Nurhadi", "fraksi": "NasDem", "dapil": "Jawa Timur VI", "provinsi": "Jawa Timur", "komisi": "IX", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Ir. Ahmad Riski Sadig M.Si.", "fraksi": "PAN", "dapil": "Jawa Timur VI", "provinsi": "Jawa Timur", "komisi": "XI", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "H. Ahmad Iman Sukri S.H., M.Hum.", "fraksi": "PKB", "dapil": "Jawa Timur VII", "provinsi": "Jawa Timur", "komisi": "XIII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Drs. Supriyanto", "fraksi": "Gerindra", "dapil": "Jawa Timur VII", "provinsi": "Jawa Timur", "komisi": "V", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Novita Hardini S.E., M.E.", "fraksi": "PDI-P", "dapil": "Jawa Timur VII", "provinsi": "Jawa Timur", "komisi": "VII", "jabatan": "Anggota"},
    {"nama": "Ir. Budi Sulistyono alias Kanang", "fraksi": "PDI-P", "dapil": "Jawa Timur VII", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Ali Mufthi S.Ag., M.Si.", "fraksi": "Golkar", "dapil": "Jawa Timur VII", "provinsi": "Jawa Timur", "komisi": "V", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Riyono S.Kel., M.Si.", "fraksi": "PKS", "dapil": "Jawa Timur VII", "provinsi": "Jawa Timur", "komisi": "IV", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Sartono S.E., M.M.", "fraksi": "Demokrat", "dapil": "Jawa Timur VII", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Dr. (H.C.) Drs. H. A. Halim Iskandar M.Pd.", "fraksi": "PKB", "dapil": "Jawa Timur VIII", "provinsi": "Jawa Timur", "komisi": "I", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Mochamad Irfan Yusuf", "fraksi": "Gerindra", "dapil": "Jawa Timur VIII", "provinsi": "Jawa Timur", "komisi": "", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Sadarestuwati S.P., M.M.A.", "fraksi": "PDI-P", "dapil": "Jawa Timur VIII", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},
    {"nama": "Banyu Biru Djarot", "fraksi": "PDI-P", "dapil": "Jawa Timur VIII", "provinsi": "Jawa Timur", "komisi": "VII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "M. Yahya Zaini S.H.", "fraksi": "Golkar", "dapil": "Jawa Timur VIII", "provinsi": "Jawa Timur", "komisi": "IX", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Muhammad Habibur Rochman S.E.", "fraksi": "NasDem", "dapil": "Jawa Timur VIII", "provinsi": "Jawa Timur", "komisi": "II", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Meitri Citra Wardani S.H.", "fraksi": "PKS", "dapil": "Jawa Timur VIII", "provinsi": "Jawa Timur", "komisi": "XII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Abdul Hakim Bafagih", "fraksi": "PAN", "dapil": "Jawa Timur VIII", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Drs. H. Guntur Sasono M.Si.", "fraksi": "Demokrat", "dapil": "Jawa Timur VIII", "provinsi": "Jawa Timur", "komisi": "IV", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Anna Mu'awanah S.E., M.H.", "fraksi": "PKB", "dapil": "Jawa Timur IX", "provinsi": "Jawa Timur", "komisi": "XI", "jabatan": "Anggota"},
    {"nama": "Hj. Ratna Juwita Sari S.E., M.M.", "fraksi": "PKB", "dapil": "Jawa Timur IX", "provinsi": "Jawa Timur", "komisi": "XII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Wihadi Wijanto S.H., M.H.", "fraksi": "Gerindra", "dapil": "Jawa Timur IX", "provinsi": "Jawa Timur", "komisi": "XI", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "H. Abidin Fikri S.H., M.H.", "fraksi": "PDI-P", "dapil": "Jawa Timur IX", "provinsi": "Jawa Timur", "komisi": "VIII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dra. Hj. Haeny Relawati Rini Widyastuti M.Si.", "fraksi": "Golkar", "dapil": "Jawa Timur IX", "provinsi": "Jawa Timur", "komisi": "VIII", "jabatan": "Anggota"},
    {"nama": "Eko Wahyudi", "fraksi": "Golkar", "dapil": "Jawa Timur IX", "provinsi": "Jawa Timur", "komisi": "IV", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Jazilul Fawaid S.Q., M.A.", "fraksi": "PKB", "dapil": "Jawa Timur X", "provinsi": "Jawa Timur", "komisi": "III", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "H. Khilmi", "fraksi": "Gerindra", "dapil": "Jawa Timur X", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "H. Nasyirul Falah Amru S.E.", "fraksi": "PDI-P", "dapil": "Jawa Timur X", "provinsi": "Jawa Timur", "komisi": "III", "jabatan": "Anggota"},
    {"nama": "Nila Yani Hardiyanti S.I.Kom.", "fraksi": "PDI-P", "dapil": "Jawa Timur X", "provinsi": "Jawa Timur", "komisi": "VII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Ahmad Labib", "fraksi": "Golkar", "dapil": "Jawa Timur X", "provinsi": "Jawa Timur", "komisi": "VI", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Jiddan S.E., S.H.", "fraksi": "NasDem", "dapil": "Jawa Timur X", "provinsi": "Jawa Timur", "komisi": "XI", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "H. Syafiuddin S.Sos., M.H.", "fraksi": "PKB", "dapil": "Jawa Timur XI", "provinsi": "Jawa Timur", "komisi": "V", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "M. H. Said Abdullah", "fraksi": "PDI-P", "dapil": "Jawa Timur XI", "provinsi": "Jawa Timur", "komisi": "XI", "jabatan": "Anggota"},
    {"nama": "Ansari S.Pd.I.", "fraksi": "PDI-P", "dapil": "Jawa Timur XI", "provinsi": "Jawa Timur", "komisi": "VIII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Eric Hermawan M.T., M.M.", "fraksi": "Golkar", "dapil": "Jawa Timur XI", "provinsi": "Jawa Timur", "komisi": "VII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Willy Aditya S.Fil., M.Ds., M.Sc.", "fraksi": "NasDem", "dapil": "Jawa Timur XI", "provinsi": "Jawa Timur", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Slamet Ariyadi S.Psi., M.Sos.", "fraksi": "PAN", "dapil": "Jawa Timur XI", "provinsi": "Jawa Timur", "komisi": "I", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "H. Hasani Bin Zuber S.IP., M.KP.", "fraksi": "Demokrat", "dapil": "Jawa Timur XI", "provinsi": "Jawa Timur", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Ahmad Fauzi", "fraksi": "PKB", "dapil": "Banten I", "provinsi": "Banten", "komisi": "V", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ali Zamroni S.Sos., M.A.P.", "fraksi": "Gerindra", "dapil": "Banten I", "provinsi": "Banten", "komisi": "X", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Adde Rosi Khoerunnisa S.Sos., M.Si.", "fraksi": "Golkar", "dapil": "Banten I", "provinsi": "Banten", "komisi": "X", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Arif Rahman", "fraksi": "NasDem", "dapil": "Banten I", "provinsi": "Banten", "komisi": "IV", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Rizki Aulia Rahman Natakusumah", "fraksi": "Demokrat", "dapil": "Banten I", "provinsi": "Banten", "komisi": "I", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Annisa M. A. Mahesa", "fraksi": "Gerindra", "dapil": "Banten II", "provinsi": "Banten", "komisi": "XI", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Sarifah Ainun Jariyah S.I.P.", "fraksi": "PDI-P", "dapil": "Banten II", "provinsi": "Banten", "komisi": "I", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Tubagus Haerul Jaman S.E.", "fraksi": "Golkar", "dapil": "Banten II", "provinsi": "Banten", "komisi": "V", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Prof. Dr. H. Furtasan Ali Yusuf S.E., S.Kom., M.M.", "fraksi": "NasDem", "dapil": "Banten II", "provinsi": "Banten", "komisi": "X", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Jazuli Juwaini M.A.", "fraksi": "PKS", "dapil": "Banten II", "provinsi": "Banten", "komisi": "I", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Edison Sitorus S.T.", "fraksi": "PAN", "dapil": "Banten II", "provinsi": "Banten", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Moh. Rano Alfath S.H., M.H.", "fraksi": "PKB", "dapil": "Banten III", "provinsi": "Banten", "komisi": "III", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Prof. H. Sufmi Dasco Ahmad", "fraksi": "Gerindra", "dapil": "Banten III", "provinsi": "Banten", "komisi": "III", "jabatan": "Wakil Ketua DPR RI"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Rano Karno", "fraksi": "PDI-P", "dapil": "Banten III", "provinsi": "Banten", "komisi": "", "jabatan": "Anggota"},
    {"nama": "Marinus Gea S.E., M.Ak.", "fraksi": "PDI-P", "dapil": "Banten III", "provinsi": "Banten", "komisi": "XIII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Airin Rachmi Diany", "fraksi": "Golkar", "dapil": "Banten III", "provinsi": "Banten", "komisi": "", "jabatan": "Anggota"},
    {"nama": "Andi Achmad Dara S.E., M.AP.", "fraksi": "Golkar", "dapil": "Banten III", "provinsi": "Banten", "komisi": "XI", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Wahidin Halim M.Si.", "fraksi": "NasDem", "dapil": "Banten III", "provinsi": "Banten", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Habib Idrus Salim Aljufri Lc., M.B.A.", "fraksi": "PKS", "dapil": "Banten III", "provinsi": "Banten", "komisi": "I", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Okta Kumala Dewi S.E., M.Ak.", "fraksi": "PAN", "dapil": "Banten III", "provinsi": "Banten", "komisi": "I", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Zulfikar Hamonangan", "fraksi": "Demokrat", "dapil": "Banten III", "provinsi": "Banten", "komisi": "XII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "I Dewa Gde Agung Widiarsana", "fraksi": "Gerindra", "dapil": "Bali", "provinsi": "Bali", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "I Nyoman Parta S.H.", "fraksi": "PDI-P", "dapil": "Bali", "provinsi": "Bali", "komisi": "X", "jabatan": "Anggota"},
    {"nama": "I Gusti Ngurah Kesuma Kelakan S.T., M.Si.", "fraksi": "PDI-P", "dapil": "Bali", "provinsi": "Bali", "komisi": "VI", "jabatan": "Anggota"},
    {"nama": "I Wayan Sudirta S.H., M.H.", "fraksi": "PDI-P", "dapil": "Bali", "provinsi": "Bali", "komisi": "III", "jabatan": "Anggota"},
    {"nama": "I Nyoman Adi Wiryatama S.Sos., M.Si.", "fraksi": "PDI-P", "dapil": "Bali", "provinsi": "Bali", "komisi": "IV", "jabatan": "Anggota"},
    {"nama": "I Ketut Kariyasa Adnyana S.P.", "fraksi": "PDI-P", "dapil": "Bali", "provinsi": "Bali", "komisi": "VIII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Gde Sumarjaya Linggih S.E., M.AP.", "fraksi": "Golkar", "dapil": "Bali", "provinsi": "Bali", "komisi": "VI", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Ir. I Nengah Senantara", "fraksi": "NasDem", "dapil": "Bali", "provinsi": "Bali", "komisi": "VI", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Ni Putu Tutik Kusuma Wardhani S.M., M.M., M.Kes.", "fraksi": "Demokrat", "dapil": "Bali", "provinsi": "Bali", "komisi": "VI", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Mahdalena S.S., M.M.", "fraksi": "PKB", "dapil": "Nusa Tenggara Barat I", "provinsi": "Nusa Tenggara Barat", "komisi": "VIII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "H. Mori Hanafi S.E.", "fraksi": "NasDem", "dapil": "Nusa Tenggara Barat I", "provinsi": "Nusa Tenggara Barat", "komisi": "V", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Johan Rosihan S.T.", "fraksi": "PKS", "dapil": "Nusa Tenggara Barat I", "provinsi": "Nusa Tenggara Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "H. Lalu Hadrian Irfani S.T.", "fraksi": "PKB", "dapil": "Nusa Tenggara Barat II", "provinsi": "Nusa Tenggara Barat", "komisi": "X", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Apt. Hj. Lale Syifaun Nufus M.Farm.", "fraksi": "Gerindra", "dapil": "Nusa Tenggara Barat II", "provinsi": "Nusa Tenggara Barat", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Rachmat Hidayat S.H.", "fraksi": "PDI-P", "dapil": "Nusa Tenggara Barat II", "provinsi": "Nusa Tenggara Barat", "komisi": "I", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Ir. Hj. Sari Yuliati M.T.", "fraksi": "Golkar", "dapil": "Nusa Tenggara Barat II", "provinsi": "Nusa Tenggara Barat", "komisi": "III", "jabatan": "Wakil Ketua DPR RI"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Fauzan Khalid S.Ag., M.Si.", "fraksi": "NasDem", "dapil": "Nusa Tenggara Barat II", "provinsi": "Nusa Tenggara Barat", "komisi": "II", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Abdul Hadi S.E., M.M.", "fraksi": "PKS", "dapil": "Nusa Tenggara Barat II", "provinsi": "Nusa Tenggara Barat", "komisi": "V", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "H. M. Muazzim Akbar S.I.P.", "fraksi": "PAN", "dapil": "Nusa Tenggara Barat II", "provinsi": "Nusa Tenggara Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Ir. H. Nanang Samodra K. A. M.Sc.", "fraksi": "Demokrat", "dapil": "Nusa Tenggara Barat II", "provinsi": "Nusa Tenggara Barat", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "N. M. Dipo Nusantara P. U. S.H., M.Kn.", "fraksi": "PKB", "dapil": "Nusa Tenggara Timur I", "provinsi": "Nusa Tenggara Timur", "komisi": "XII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Andreas Hugo Pareira", "fraksi": "PDI-P", "dapil": "Nusa Tenggara Timur I", "provinsi": "Nusa Tenggara Timur", "komisi": "XIII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Melchias Marcus Mekeng M.H.", "fraksi": "Golkar", "dapil": "Nusa Tenggara Timur I", "provinsi": "Nusa Tenggara Timur", "komisi": "XI", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Julie Sutrisno Laiskodat", "fraksi": "NasDem", "dapil": "Nusa Tenggara Timur I", "provinsi": "Nusa Tenggara Timur", "komisi": "XI", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Ahmad Yohan M.Si.", "fraksi": "PAN", "dapil": "Nusa Tenggara Timur I", "provinsi": "Nusa Tenggara Timur", "komisi": "IV", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Benny Kabur Harman S.H.", "fraksi": "Demokrat", "dapil": "Nusa Tenggara Timur I", "provinsi": "Nusa Tenggara Timur", "komisi": "III", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Usman Husin", "fraksi": "PKB", "dapil": "Nusa Tenggara Timur II", "provinsi": "Nusa Tenggara Timur", "komisi": "IV", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Ir. Esthon L. Foenay M.Si.", "fraksi": "Gerindra", "dapil": "Nusa Tenggara Timur II", "provinsi": "Nusa Tenggara Timur", "komisi": "II", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Yohanis Fransiskus Lema", "fraksi": "PDI-P", "dapil": "Nusa Tenggara Timur II", "provinsi": "Nusa Tenggara Timur", "komisi": "", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Emanuel Melkiades Laka Lena", "fraksi": "Golkar", "dapil": "Nusa Tenggara Timur II", "provinsi": "Nusa Tenggara Timur", "komisi": "", "jabatan": "Anggota"},
    {"nama": "Gavriel Putranto Novanto", "fraksi": "Golkar", "dapil": "Nusa Tenggara Timur II", "provinsi": "Nusa Tenggara Timur", "komisi": "I", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Anita Jacoba Gah", "fraksi": "Demokrat", "dapil": "Nusa Tenggara Timur II", "provinsi": "Nusa Tenggara Timur", "komisi": "X", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Daniel Johan", "fraksi": "PKB", "dapil": "Kalimantan Barat I", "provinsi": "Kalimantan Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Yuliansyah S.E.", "fraksi": "Gerindra", "dapil": "Kalimantan Barat I", "provinsi": "Kalimantan Barat", "komisi": "V", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Drs. Cornelis M.H.", "fraksi": "PDI-P", "dapil": "Kalimantan Barat I", "provinsi": "Kalimantan Barat", "komisi": "XII", "jabatan": "Anggota"},
    {"nama": "Maria Lestari S.Pd., M.H.", "fraksi": "PDI-P", "dapil": "Kalimantan Barat I", "provinsi": "Kalimantan Barat", "komisi": "VII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Maman Abdurrahman S.T.", "fraksi": "Golkar", "dapil": "Kalimantan Barat I", "provinsi": "Kalimantan Barat", "komisi": "XIII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "H. Syarief Abdullah Alkadrie S.H.", "fraksi": "NasDem", "dapil": "Kalimantan Barat I", "provinsi": "Kalimantan Barat", "komisi": "V", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "H. Alifudin S.E., M.M.", "fraksi": "PKS", "dapil": "Kalimantan Barat I", "provinsi": "Kalimantan Barat", "komisi": "IX", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Boyman Harun S.H.", "fraksi": "PAN", "dapil": "Kalimantan Barat I", "provinsi": "Kalimantan Barat", "komisi": "V", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Lasarus S.Sos., M.Si.", "fraksi": "PDI-P", "dapil": "Kalimantan Barat II", "provinsi": "Kalimantan Barat", "komisi": "V", "jabatan": "Anggota"},
    {"nama": "Paolus Hadi S.IP., M.Si.", "fraksi": "PDI-P", "dapil": "Kalimantan Barat II", "provinsi": "Kalimantan Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Drs. Adrianus Asia Sidot M.Si.", "fraksi": "Golkar", "dapil": "Kalimantan Barat II", "provinsi": "Kalimantan Barat", "komisi": "IV", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Gulam Mohamad Sharon", "fraksi": "NasDem", "dapil": "Kalimantan Barat II", "provinsi": "Kalimantan Barat", "komisi": "XII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "H. Iwan Kurniawan", "fraksi": "Gerindra", "dapil": "Kalimantan Tengah", "provinsi": "Kalimantan Tengah", "komisi": "II", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Agustiar Sabran", "fraksi": "PDI-P", "dapil": "", "provinsi": "Kalimantan Tengah", "komisi": "", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Drs. Mukhtarudin", "fraksi": "Golkar", "dapil": "", "provinsi": "Kalimantan Tengah", "komisi": "XII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Andina Thresia Narang B.Comm.", "fraksi": "NasDem", "dapil": "", "provinsi": "Kalimantan Tengah", "komisi": "I", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Muhammad Syauqie S.Hut.", "fraksi": "PAN", "dapil": "", "provinsi": "Kalimantan Tengah", "komisi": "V", "jabatan": "Anggota"},
    {"nama": "Nadalsyah", "fraksi": "PAN", "dapil": "", "provinsi": "Kalimantan Tengah", "komisi": "", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Muhammad Rofiqi S.H.", "fraksi": "Gerindra", "dapil": "Kalimantan Selatan I", "provinsi": "Kalimantan Selatan", "komisi": "III", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Drs. H. Bambang Heri Purnama S.T., S.H., M.H.", "fraksi": "Golkar", "dapil": "Kalimantan Selatan I", "provinsi": "Kalimantan Selatan", "komisi": "I", "jabatan": "Anggota"},
    {"nama": "Sandi Fitrian Noor S.T., M.M.", "fraksi": "Golkar", "dapil": "Kalimantan Selatan I", "provinsi": "Kalimantan Selatan", "komisi": "VIII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. M. Rifqinizamy Karsayuda S.H., M.H.", "fraksi": "NasDem", "dapil": "Kalimantan Selatan I", "provinsi": "Kalimantan Selatan", "komisi": "II", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Ir. Pangeran Khairul Saleh M.M.", "fraksi": "PAN", "dapil": "Kalimantan Selatan I", "provinsi": "Kalimantan Selatan", "komisi": "XIII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Mariana S.A.B., M.M.", "fraksi": "Gerindra", "dapil": "Kalimantan Selatan II", "provinsi": "Kalimantan Selatan", "komisi": "IX", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Hasnuryadi Sulaiman", "fraksi": "Golkar", "dapil": "", "provinsi": "Kalimantan Selatan", "komisi": "", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Endang Agustina S.Sos., M.H.", "fraksi": "PAN", "dapil": "", "provinsi": "Kalimantan Selatan", "komisi": "III", "jabatan": "Anggota"},
    {"nama": "Sudian Noor", "fraksi": "PAN", "dapil": "", "provinsi": "Kalimantan Selatan", "komisi": "VIII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Syafruddin S.Pd.", "fraksi": "PKB", "dapil": "Kalimantan Timur", "provinsi": "Kalimantan Timur", "komisi": "XII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "G. Budisatrio Djiwandono", "fraksi": "Gerindra", "dapil": "Kalimantan Timur", "provinsi": "Kalimantan Timur", "komisi": "I", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Drs. Safaruddin M.I.Kom.", "fraksi": "PDI-P", "dapil": "Kalimantan Timur", "provinsi": "Kalimantan Timur", "komisi": "III", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Rudy Mas'ud", "fraksi": "Golkar", "dapil": "", "provinsi": "Kalimantan Timur", "komisi": "", "jabatan": "Anggota"},
    {"nama": "Dr. Ir. Hetifah Sjaifudian M.P.P.", "fraksi": "Golkar", "dapil": "", "provinsi": "Kalimantan Timur", "komisi": "X", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Nabil Husien Said Amin Alrasydi", "fraksi": "NasDem", "dapil": "", "provinsi": "Kalimantan Timur", "komisi": "III", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "K. H. Aus Hidayat Nur", "fraksi": "PKS", "dapil": "", "provinsi": "Kalimantan Timur", "komisi": "II", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Edi Oloan Pasaribu S.T., M.M.", "fraksi": "PAN", "dapil": "", "provinsi": "Kalimantan Timur", "komisi": "II", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Rahmawati S.H.", "fraksi": "Gerindra", "dapil": "Kalimantan Utara", "provinsi": "Kalimantan Utara", "komisi": "VII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Ir. Deddy Yevri Hanteru Sitorus M.A.", "fraksi": "PDI-P", "dapil": "Kalimantan Utara", "provinsi": "Kalimantan Utara", "komisi": "II", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Drs. Hasan Saleh", "fraksi": "Demokrat", "dapil": "Kalimantan Utara", "provinsi": "Kalimantan Utara", "komisi": "IV", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "dr. Christovel Liempepas", "fraksi": "Gerindra", "dapil": "Sulawesi Utara", "provinsi": "[[Sulawesi Utara]]", "komisi": "", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Rio Alexander Jeremia Dondokambey B.Sc., M.M", "fraksi": "PDI-P", "dapil": "Sulawesi Utara", "provinsi": "[[Sulawesi Utara]]", "komisi": "XI", "jabatan": "Anggota"},
    {"nama": "Dra. Yasti Soepredjo Mokoagow", "fraksi": "PDI-P", "dapil": "Sulawesi Utara", "provinsi": "[[Sulawesi Utara]]", "komisi": "V", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Christiany Eugenia Paruntu S.E., M.Th", "fraksi": "Golkar", "dapil": "Sulawesi Utara", "provinsi": "[[Sulawesi Utara]]", "komisi": "XII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Felly Estelita Runtuwene S.E.", "fraksi": "NasDem", "dapil": "Sulawesi Utara", "provinsi": "[[Sulawesi Utara]]", "komisi": "IX", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hillary Brigitta Lasut S.H., LL.M.", "fraksi": "Demokrat", "dapil": "Sulawesi Utara", "provinsi": "[[Sulawesi Utara]]", "komisi": "XI", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Drs. H. Longki Djanggola M.Si.", "fraksi": "Gerindra", "dapil": "Sulawesi Tengah", "provinsi": "[[Sulawesi Tengah]]", "komisi": "II", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Matindas Janusanti Rumambi S.Sos.", "fraksi": "PDI-P", "dapil": "Sulawesi Tengah", "provinsi": "[[Sulawesi Tengah]]", "komisi": "VIII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "H. Muhidin Mohamad Said", "fraksi": "Golkar", "dapil": "Sulawesi Tengah", "provinsi": "[[Sulawesi Tengah]]", "komisi": "XI", "jabatan": "Anggota"},
    {"nama": "Ir. Beniyanto S.T.", "fraksi": "Golkar", "dapil": "Sulawesi Tengah", "provinsi": "[[Sulawesi Tengah]]", "komisi": "VII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Nilam Sari Lawira S.P., M.P.", "fraksi": "NasDem", "dapil": "Sulawesi Tengah", "provinsi": "[[Sulawesi Tengah]]", "komisi": "X", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Sarifuddin Sudding S.H., M.H.", "fraksi": "PAN", "dapil": "Sulawesi Tengah", "provinsi": "[[Sulawesi Tengah]]", "komisi": "III", "jabatan": "Anggota"},
    {"nama": "Anwar Hafid", "fraksi": "PAN", "dapil": "Sulawesi Tengah", "provinsi": "[[Sulawesi Tengah]]", "komisi": "", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Syamsu Rizal M. I. S.Sos., M.Si.", "fraksi": "PKB", "dapil": "Sulawesi Selatan I", "provinsi": "[[Sulawesi Selatan]]", "komisi": "I", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Dr. H. Azikin Solthan M.Si.", "fraksi": "Gerindra", "dapil": "Sulawesi Selatan I", "provinsi": "[[Sulawesi Selatan]]", "komisi": "VII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Ridwan Andi Wittiri S.H.", "fraksi": "PDI-P", "dapil": "Sulawesi Selatan I", "provinsi": "[[Sulawesi Selatan]]", "komisi": "XII", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Drs. Hamka B. Kady M.S.", "fraksi": "Golkar", "dapil": "Sulawesi Selatan I", "provinsi": "[[Sulawesi Selatan]]", "komisi": "V", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Rudianto Lallo S.H.", "fraksi": "NasDem", "dapil": "Sulawesi Selatan I", "provinsi": "[[Sulawesi Selatan]]", "komisi": "III", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Hj. Meity Rahmatia S.E., S.Pd., M.M.", "fraksi": "PKS", "dapil": "Sulawesi Selatan I", "provinsi": "[[Sulawesi Selatan]]", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Drs. H. Ashabul Kahfi M.Ag.", "fraksi": "PAN", "dapil": "Sulawesi Selatan I", "provinsi": "[[Sulawesi Selatan]]", "komisi": "IX", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Drs. H. Andi Muawiyah Ramly M.Si.", "fraksi": "PKB", "dapil": "Sulawesi Selatan II", "provinsi": "[[Sulawesi Selatan]]", "komisi": "X", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Andi Amar Ma'ruf Sulaiman S.E.", "fraksi": "Gerindra", "dapil": "Sulawesi Selatan II", "provinsi": "[[Sulawesi Selatan]]", "komisi": "III", "jabatan": "Anggota"},
    {"nama": "H. Andi Iwan Darmawan Aras S.E., M.Si.", "fraksi": "Gerindra", "dapil": "Sulawesi Selatan II", "provinsi": "[[Sulawesi Selatan]]", "komisi": "V", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "A. M. Nurdin Halid", "fraksi": "Golkar", "dapil": "Sulawesi Selatan II", "provinsi": "[[Sulawesi Selatan]]", "komisi": "VI", "jabatan": "Anggota"},
    {"nama": "Dr. H. M. Taufan Pawe S.H., M.H.", "fraksi": "Golkar", "dapil": "Sulawesi Selatan II", "provinsi": "[[Sulawesi Selatan]]", "komisi": "II", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Teguh Iswara Suardi", "fraksi": "NasDem", "dapil": "Sulawesi Selatan II", "provinsi": "[[Sulawesi Selatan]]", "komisi": "V", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Ismail", "fraksi": "PKS", "dapil": "Sulawesi Selatan II", "provinsi": "[[Sulawesi Selatan]]", "komisi": "VI", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Hj. Andi Yuliani Paris", "fraksi": "PAN", "dapil": "Sulawesi Selatan II", "provinsi": "[[Sulawesi Selatan]]", "komisi": "XI", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Andi Muzakkir Aqil", "fraksi": "Demokrat", "dapil": "Sulawesi Selatan II", "provinsi": "[[Sulawesi Selatan]]", "komisi": "III", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Unru Baso", "fraksi": "Gerindra", "dapil": "Sulawesi Selatan III", "provinsi": "[[Sulawesi Selatan]]", "komisi": "VI", "jabatan": "Anggota"},
    {"nama": "Ir. H. La Tinro La Tunrung", "fraksi": "Gerindra", "dapil": "Sulawesi Selatan III", "provinsi": "[[Sulawesi Selatan]]", "komisi": "X", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Muhammad Fauzi S.E.", "fraksi": "Golkar", "dapil": "Sulawesi Selatan III", "provinsi": "[[Sulawesi Selatan]]", "komisi": "", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "H. Rusdi Masse Mappasessu", "fraksi": "NasDem", "dapil": "Sulawesi Selatan III", "provinsi": "[[Sulawesi Selatan]]", "komisi": "III", "jabatan": "Anggota"},
    {"nama": "Eva Stevany Rataba S.H.", "fraksi": "NasDem", "dapil": "Sulawesi Selatan III", "provinsi": "[[Sulawesi Selatan]]", "komisi": "X", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Drs. H. Muslimin Bando M.Pd.", "fraksi": "PAN", "dapil": "Sulawesi Selatan III", "provinsi": "[[Sulawesi Selatan]]", "komisi": "X", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Irjen. Pol. (Purn.) Drs. Frederik Kalalembang", "fraksi": "Demokrat", "dapil": "Sulawesi Selatan III", "provinsi": "[[Sulawesi Selatan]]", "komisi": "I", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Jaelani S.IP., M.Si.", "fraksi": "PKB", "dapil": "Sulawesi Tenggara", "provinsi": "[[Sulawesi Tenggara]]", "komisi": "IV", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Bahtra S.PWK.", "fraksi": "Gerindra", "dapil": "Sulawesi Tenggara", "provinsi": "[[Sulawesi Tenggara]]", "komisi": "II", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "H. Ahmad Safei S.H., M.H.", "fraksi": "PDI-P", "dapil": "Sulawesi Tenggara", "provinsi": "[[Sulawesi Tenggara]]", "komisi": "IX", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Ir. Ridwan Bae", "fraksi": "Golkar", "dapil": "Sulawesi Tenggara", "provinsi": "[[Sulawesi Tenggara]]", "komisi": "V", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Rusda Mahmud", "fraksi": "Demokrat", "dapil": "Sulawesi Tenggara", "provinsi": "[[Sulawesi Tenggara]]", "komisi": "II", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Elnino M. Husein Mohi S.T., M.Si.", "fraksi": "Gerindra", "dapil": "Gorontalo", "provinsi": "[[Gorontalo]]", "komisi": "I", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Drs. H. Rusli Habibie M.A.P.", "fraksi": "Golkar", "dapil": "Gorontalo", "provinsi": "[[Gorontalo]]", "komisi": "XII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Dr. (H.C.) H. Rachmad Gobel", "fraksi": "NasDem", "dapil": "Gorontalo", "provinsi": "[[Gorontalo]]", "komisi": "VI", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Ir. H. Agus Ambo Djiwa M.P.", "fraksi": "PDI-P", "dapil": "Sulawesi Barat", "provinsi": "[[Sulawesi Barat]]", "komisi": "IV", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Ratih Megasari Singkarru M.Sc.", "fraksi": "NasDem", "dapil": "Sulawesi Barat", "provinsi": "[[Sulawesi Barat]]", "komisi": "X", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Ajbar S.P.", "fraksi": "PAN", "dapil": "Sulawesi Barat", "provinsi": "[[Sulawesi Barat]]", "komisi": "IV", "jabatan": "Anggota"},
    {"nama": "Suhardi Duka", "fraksi": "PAN", "dapil": "Sulawesi Barat", "provinsi": "[[Sulawesi Barat]]", "komisi": "", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Hendrik Lewerissa", "fraksi": "Gerindra", "dapil": "Maluku", "provinsi": "[[Maluku]]", "komisi": "", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Mercy Chriesty Barends S.T.", "fraksi": "PDI-P", "dapil": "Maluku", "provinsi": "[[Maluku]]", "komisi": "X", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Saadiah Uluputty S.T.", "fraksi": "PKS", "dapil": "Maluku", "provinsi": "[[Maluku]]", "komisi": "IV", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Widya Pratiwi", "fraksi": "PAN", "dapil": "Maluku", "provinsi": "[[Maluku]]", "komisi": "III", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Irine Yusiana Roba Putri S.Sos., M.Comn&MediaSt.", "fraksi": "PDI-P", "dapil": "Maluku Utara", "provinsi": "[[Maluku Utara]]", "komisi": "V", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Alien Mus S.Sos.", "fraksi": "Golkar", "dapil": "Maluku Utara", "provinsi": "[[Maluku Utara]]", "komisi": "IV", "jabatan": "Anggota"},

    # ── PKS (53 kursi) ──────────────────────────────────────────
    {"nama": "Izzuddin Alqassam Kasuba", "fraksi": "PKS", "dapil": "Maluku Utara", "provinsi": "[[Maluku Utara]]", "komisi": "VII", "jabatan": "Anggota"},

    # ── Gerindra (86 kursi) ──────────────────────────────────────────
    {"nama": "Yan Permenas Mandenas S.Sos., M.Si.", "fraksi": "Gerindra", "dapil": "Papua", "provinsi": "[[Papua]]", "komisi": "XIII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Benhur Tomi Mano", "fraksi": "PDI-P", "dapil": "", "provinsi": "[[Papua]]", "komisi": "", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Tonny Tesar S.Sos.", "fraksi": "NasDem", "dapil": "", "provinsi": "[[Papua]]", "komisi": "VII", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Obet Rumbruren", "fraksi": "PDI-P", "dapil": "Papua Barat", "provinsi": "[[Papua Barat]]", "komisi": "IX", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "drg. Alfons Manibui", "fraksi": "Golkar", "dapil": "Papua Barat", "provinsi": "[[Papua Barat]]", "komisi": "XII", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Cheroline Chrisye Makalew", "fraksi": "NasDem", "dapil": "Papua Barat", "provinsi": "[[Papua Barat]]", "komisi": "XII", "jabatan": "Anggota"},

    # ── PKB (68 kursi) ──────────────────────────────────────────
    {"nama": "Kristosimus Yohanes Agawemu", "fraksi": "PKB", "dapil": "Papua Selatan", "provinsi": "[[Papua Selatan]]", "komisi": "", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Edoardus Kaize", "fraksi": "PDI-P", "dapil": "Papua Selatan", "provinsi": "[[Papua Selatan]]", "komisi": "IV", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Dr. (H.C.) H. Sulaeman L. Hamzah", "fraksi": "NasDem", "dapil": "Papua Selatan", "provinsi": "[[Papua Selatan]]", "komisi": "IV", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "Kamarudin Watubun S.H., M.H.", "fraksi": "PDI-P", "dapil": "Papua Tengah", "provinsi": "[[Papua Tengah]]", "komisi": "II", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Dr. Soedeson Tandra S.H., M.Hum.", "fraksi": "Golkar", "dapil": "Papua Tengah", "provinsi": "[[Papua Tengah]]", "komisi": "III", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Natalis Tabuni S.S., M.Si.", "fraksi": "NasDem", "dapil": "Papua Tengah", "provinsi": "[[Papua Tengah]]", "komisi": "", "jabatan": "Anggota"},

    # ── PDI-P (110 kursi) ──────────────────────────────────────────
    {"nama": "John Wempi Wetipo", "fraksi": "PDI-P", "dapil": "Papua Pegunungan", "provinsi": "[[Papua Pegunungan]]", "komisi": "", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Roberth Rouw", "fraksi": "NasDem", "dapil": "Papua Pegunungan", "provinsi": "[[Papua Pegunungan]]", "komisi": "V", "jabatan": "Anggota"},

    # ── PAN (53 kursi) ──────────────────────────────────────────
    {"nama": "Paulus Ubruangge", "fraksi": "PAN", "dapil": "Papua Pegunungan", "provinsi": "[[Papua Pegunungan]]", "komisi": "IX", "jabatan": "Anggota"},

    # ── Golkar (102 kursi) ──────────────────────────────────────────
    {"nama": "Robert Joppy Kardinal S.A.B.", "fraksi": "Golkar", "dapil": "Papua Barat Daya", "provinsi": "[[Papua Barat Daya]]", "komisi": "IV", "jabatan": "Anggota"},

    # ── NasDem (69 kursi) ──────────────────────────────────────────
    {"nama": "Rico Sia M.Si.", "fraksi": "NasDem", "dapil": "Papua Barat Daya", "provinsi": "[[Papua Barat Daya]]", "komisi": "VII", "jabatan": "Anggota"},

    # ── Demokrat (39 kursi) ──────────────────────────────────────────
    {"nama": "Faujia Helga Br. Tampubolon", "fraksi": "Demokrat", "dapil": "Papua Barat Daya", "provinsi": "[[Papua Barat Daya]]", "komisi": "VI", "jabatan": "Anggota"},
]

# Pimpinan DPR RI 2024-2029 (update per Mei 2026: Adela Kanasya Adies PAW Adies Kadir)
PIMPINAN_DPR = [
    {"jabatan": "Ketua DPR RI",         "nama": "Puan Maharani",              "fraksi": "PDI-P"},
    {"jabatan": "Wakil Ketua DPR RI",   "nama": "Sufmi Dasco Ahmad",          "fraksi": "Gerindra"},
    {"jabatan": "Wakil Ketua DPR RI",   "nama": "Saan Mustopa",               "fraksi": "NasDem"},
    {"jabatan": "Wakil Ketua DPR RI",   "nama": "Cucun Ahmad Syamsurijal",    "fraksi": "PKB"},
    {"jabatan": "Wakil Ketua DPR RI",   "nama": "Sari Yuliati",               "fraksi": "Golkar"},
]

# Komisi DPR RI
KOMISI_DPR = {
    "I":   "Pertahanan, Intelijen, Luar Negeri, Komunikasi & Informatika",
    "II":  "Pemerintahan Dalam Negeri, Otonomi Daerah, Aparatur Negara, Agraria",
    "III": "Hukum, HAM, Keamanan",
    "IV":  "Pertanian, Perkebunan, Kehutanan, Kelautan, Perikanan, Pangan",
    "V":   "Perhubungan, Pekerjaan Umum, Perumahan Rakyat, Telekomunikasi",
    "VI":  "Perdagangan, Perindustrian, Investasi, Koperasi, BUMN",
    "VII": "Energi, Riset & Teknologi, Lingkungan Hidup",
    "VIII":"Agama, Sosial, Pemberdayaan Perempuan",
    "IX":  "Ketenagakerjaan, Kependudukan, Kesehatan",
    "X":   "Pendidikan, Pemuda, Olahraga, Pariwisata",
    "XI":  "Keuangan, Perbankan, Perencanaan Pembangunan Nasional",
}

CSV_FIELDS = ["nama", "fraksi", "dapil", "provinsi", "komisi", "bidang_komisi", "jabatan"]


def build_rows() -> list[dict]:
    rows = []
    for a in ANGGOTA_DPR:
        komisi = a.get("komisi", "")
        rows.append({
            "nama":          a["nama"],
            "fraksi":        a["fraksi"],
            "dapil":         a["dapil"],
            "provinsi":      a["provinsi"],
            "komisi":        komisi,
            "bidang_komisi": KOMISI_DPR.get(komisi, "-"),
            "jabatan":       a.get("jabatan", "Anggota"),
        })
    return rows


def filter_rows(rows: list[dict], fraksi_filter: list[str] | None) -> list[dict]:
    if not fraksi_filter:
        return rows
    fraksi_up = [f.upper() for f in fraksi_filter]
    return [r for r in rows if r["fraksi"].upper() in fraksi_up]


def save_csv(rows: list[dict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    logger.info(f"CSV disimpan: {path} ({len(rows)} anggota)")


def save_json(rows: list[dict], path: Path) -> None:
    data = {
        "meta": {
            "periode":      "2024-2029",
            "total_kursi":  580,
            "total_data":   len(rows),
            "fraksi":       FRAKSI_KURSI,
            "komisi":       KOMISI_DPR,
        },
        "pimpinan": PIMPINAN_DPR,
        "anggota":  rows,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"JSON disimpan: {path}")


def save_txt(rows: list[dict], path: Path) -> None:
    from collections import Counter
    per_fraksi: Counter = Counter(r["fraksi"] for r in rows)
    per_komisi: Counter = Counter(r["komisi"] for r in rows if r["komisi"] not in ("-", "Pimpinan"))
    per_prov: Counter   = Counter(r["provinsi"] for r in rows)

    lines = [
        "=" * 65,
        "  DATA ANGGOTA DPR RI PERIODE 2024-2029",
        "=" * 65,
        f"\nTotal kursi resmi : 580",
        f"Total data ini    : {len(rows)}",
        "",
        "PIMPINAN DPR RI:",
    ]
    for p in PIMPINAN_DPR:
        lines.append(f"  {p['jabatan']:<28} {p['nama']} ({p['fraksi']})")
    lines += ["", "KOMPOSISI KURSI PER FRAKSI (580 total):"]
    for fr, k in sorted(FRAKSI_KURSI.items(), key=lambda x: -x[1]):
        if k > 0:
            lines.append(f"  {fr:<12}  {k:>3} kursi")
    lines += ["", "DATA PER FRAKSI (dalam file ini):"]
    for fr, n in sorted(per_fraksi.items(), key=lambda x: -x[1]):
        lines.append(f"  {fr:<12}  {n:>3} anggota")
    lines += ["", "PER KOMISI:"]
    for km, n in sorted(per_komisi.items()):
        bidang = KOMISI_DPR.get(km, "")
        lines.append(f"  Komisi {km:<4}  {n:>2} anggota  -- {bidang[:45]}")
    lines += ["", "PER PROVINSI:"]
    for prov, n in sorted(per_prov.items(), key=lambda x: -x[1]):
        lines.append(f"  {prov:<35}  {n:>3}")
    lines += ["", "=" * 65, "Sumber: KPU RI, dpr.go.id (data publik)", "=" * 65]
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Ringkasan disimpan: {path}")


def print_list(rows: list[dict]) -> None:
    fraksi_curr = None
    for r in sorted(rows, key=lambda x: (x["fraksi"], x["nama"])):
        if r["fraksi"] != fraksi_curr:
            fraksi_curr = r["fraksi"]
            print(f"\n-- {fraksi_curr} --")
        print(f"  {r['nama']:<40} Dapil: {r['dapil']:<25} Komisi {r['komisi']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Data Anggota DPR RI 2024-2029")
    parser.add_argument("--fraksi", nargs="*", help="Filter fraksi: Golkar PDIP Gerindra PKB Nasdem PKS Demokrat PAN")
    parser.add_argument("--json",   action="store_true", help="Simpan JSON")
    parser.add_argument("--list",   action="store_true", help="Tampilkan daftar di terminal")
    args = parser.parse_args()

    rows = build_rows()
    rows = filter_rows(rows, args.fraksi)

    out_dir = Path(__file__).parent

    save_csv(rows,            out_dir / "dpr_indonesia.csv")
    save_txt(rows,            out_dir / "dpr_indonesia.txt")
    if args.json:
        save_json(rows,       out_dir / "dpr_indonesia.json")
    if args.list:
        print_list(rows)

    print(f"\nSELESAI -- {len(rows)} anggota DPR RI 2024-2029 disimpan.")
    print("Sumber: Wikipedia ID (https://id.wikipedia.org/wiki/Daftar_anggota_DPR_RI_2024-2029)")
    print("Catatan: 556 dari 580 kursi berhasil diparsing (24 entri tidak terparsing akibat format wiki).")
    print("         Untuk data resmi: https://www.dpr.go.id/anggota")


if __name__ == "__main__":
    main()
