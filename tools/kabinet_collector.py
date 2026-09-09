"""
kabinet_collector.py - Data Kabinet & Menteri Indonesia (1945-2029)
Sumber data: disusun dari Wikipedia, Setneg, dan sumber resmi pemerintah.
Data embedded langsung (tidak butuh internet, selalu tersedia).

Output:
  kabinet_indonesia.csv   - semua menteri (Excel-ready)
  kabinet_indonesia.txt   - ringkasan per presiden

Cara pakai:
  python kabinet_collector.py
  python kabinet_collector.py --presiden Jokowi
  python kabinet_collector.py --list
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

# ── DATA EMBEDDED ──────────────────────────────────────────────────────────────
# Format: {kabinet, presiden, periode, menteri: [{nama, jabatan}]}
# Sumber: Wikipedia ID, Setneg, Sekretariat Kabinet RI
KABINET_DATA: list[dict] = [
  # ───────────────────────────── SOEKARNO ─────────────────────────────────────
  {
    "kabinet": "Kabinet Presidensial",
    "presiden": "Soekarno",
    "periode": "2 September 1945 - 14 November 1945",
    "menteri": [
      {"nama": "Soekarno",                    "jabatan": "Presiden / Perdana Menteri"},
      {"nama": "Moh. Hatta",                  "jabatan": "Wakil Presiden"},
      {"nama": "R.A.A. Wiranatakoesoema",     "jabatan": "Menteri Dalam Negeri"},
      {"nama": "Ahmad Soebardjo",             "jabatan": "Menteri Luar Negeri"},
      {"nama": "Soepomo",                     "jabatan": "Menteri Kehakiman"},
      {"nama": "Ki Hadjar Dewantara",         "jabatan": "Menteri Pengajaran"},
      {"nama": "Iwa Koesoemasoemantri",       "jabatan": "Menteri Sosial"},
      {"nama": "Soerjohamidjojo",             "jabatan": "Menteri Kesehatan"},
      {"nama": "Soeprijadi",                  "jabatan": "Menteri Keamanan Rakyat"},
      {"nama": "Abikusno Tjokrosoejoso",      "jabatan": "Menteri Perhubungan"},
      {"nama": "Djoeanda Kartawidjaja",       "jabatan": "Menteri Kemakmuran"},
      {"nama": "A.A. Maramis",                "jabatan": "Menteri Keuangan"},
      {"nama": "Wachid Hasjim",               "jabatan": "Menteri Agama"},
      {"nama": "Amir Sjarifuddin",            "jabatan": "Menteri Penerangan"},
      {"nama": "Chaerul Saleh",               "jabatan": "Menteri Negara"},
      {"nama": "Otto Iskandardinata",         "jabatan": "Menteri Negara"},
    ],
  },
  # ───────────────────────────── HABIBIE ──────────────────────────────────────
  {
    "kabinet": "Kabinet Reformasi Pembangunan",
    "presiden": "BJ Habibie",
    "periode": "23 Mei 1998 - 20 Oktober 1999",
    "menteri": [
      {"nama": "BJ Habibie",                  "jabatan": "Presiden"},
      {"nama": "Wiranto",                     "jabatan": "Menteri Pertahanan & Keamanan / Panglima ABRI"},
      {"nama": "Ali Alatas",                  "jabatan": "Menteri Luar Negeri"},
      {"nama": "Syarwan Hamid",               "jabatan": "Menteri Dalam Negeri"},
      {"nama": "Muladi",                      "jabatan": "Menteri Kehakiman"},
      {"nama": "Bambang Subianto",            "jabatan": "Menteri Keuangan"},
      {"nama": "Ginandjar Kartasasmita",      "jabatan": "Menteri Koordinator Bidang Ekonomi"},
      {"nama": "Feisal Tamin",                "jabatan": "Menteri Pendayagunaan Aparatur Negara"},
      {"nama": "Fahmi Idris",                 "jabatan": "Menteri Tenaga Kerja"},
      {"nama": "Akbar Tandjung",              "jabatan": "Menteri Sekretaris Negara"},
      {"nama": "Hamzah Haz",                  "jabatan": "Menteri Koordinator Bidang Kesejahteraan Rakyat"},
      {"nama": "Andi Mappi Sammeng",          "jabatan": "Menteri Pariwisata, Seni dan Budaya"},
      {"nama": "Juwono Sudarsono",            "jabatan": "Menteri Pendidikan dan Kebudayaan"},
      {"nama": "Farid Anfasa Moeloek",        "jabatan": "Menteri Kesehatan"},
      {"nama": "Theo L. Sambuaga",            "jabatan": "Menteri Perumahan Rakyat"},
      {"nama": "Rahardi Ramelan",             "jabatan": "Menteri Pertambangan dan Energi"},
      {"nama": "Hartarto Sastrosoenarto",     "jabatan": "Menteri Perindustrian dan Perdagangan"},
      {"nama": "Mohamad Sadli",               "jabatan": "Menteri Negara Koordinator Bidang Produksi dan Distribusi"},
    ],
  },
  # ───────────────────────────── GUS DUR ──────────────────────────────────────
  {
    "kabinet": "Kabinet Persatuan Nasional",
    "presiden": "Abdurrahman Wahid",
    "periode": "26 Oktober 1999 - 23 Juli 2001",
    "menteri": [
      {"nama": "Abdurrahman Wahid",           "jabatan": "Presiden"},
      {"nama": "Megawati Soekarnoputri",      "jabatan": "Wakil Presiden"},
      {"nama": "Wiranto",                     "jabatan": "Menteri Koordinator Bidang Politik dan Keamanan"},
      {"nama": "Kwik Kian Gie",               "jabatan": "Menteri Koordinator Bidang Ekonomi"},
      {"nama": "Hamzah Haz",                  "jabatan": "Menteri Koordinator Bidang Kesejahteraan Rakyat"},
      {"nama": "Sarwono Kusumaatmadja",       "jabatan": "Menteri Eksplorasi Kelautan"},
      {"nama": "Alwi Shihab",                 "jabatan": "Menteri Luar Negeri"},
      {"nama": "Mahfud MD",                   "jabatan": "Menteri Pertahanan"},
      {"nama": "Surjadi Soedirdja",           "jabatan": "Menteri Dalam Negeri"},
      {"nama": "Yusril Ihza Mahendra",        "jabatan": "Menteri Hukum dan Perundang-Undangan"},
      {"nama": "Bambang Sudibyo",             "jabatan": "Menteri Keuangan"},
      {"nama": "Prijadi Praptosuhardjo",      "jabatan": "Menteri Perdagangan dan Industri"},
      {"nama": "Bungaran Saragih",            "jabatan": "Menteri Pertanian"},
      {"nama": "Susilo Bambang Yudhoyono",    "jabatan": "Menteri Koordinator Bidang Politik, Sosial, dan Keamanan"},
      {"nama": "Mohammad Mahfud",             "jabatan": "Menteri Negara HAM"},
      {"nama": "Khofifah Indar Parawansa",    "jabatan": "Menteri Negara Pemberdayaan Perempuan"},
      {"nama": "Goenawan Mohamad",            "jabatan": "Menteri Negara Urusan Komunikasi"},
      {"nama": "Eko Budiharjo",               "jabatan": "Menteri Negara Perumahan dan Permukiman"},
    ],
  },
  # ───────────────────────────── MEGAWATI ─────────────────────────────────────
  {
    "kabinet": "Kabinet Gotong Royong",
    "presiden": "Megawati Soekarnoputri",
    "periode": "9 Agustus 2001 - 20 Oktober 2004",
    "menteri": [
      {"nama": "Megawati Soekarnoputri",      "jabatan": "Presiden"},
      {"nama": "Hamzah Haz",                  "jabatan": "Wakil Presiden"},
      {"nama": "Susilo Bambang Yudhoyono",    "jabatan": "Menko Politik dan Keamanan"},
      {"nama": "Dorodjatun Kuntjoro-Jakti",   "jabatan": "Menko Bidang Perekonomian"},
      {"nama": "Jusuf Kalla",                 "jabatan": "Menko Kesejahteraan Rakyat"},
      {"nama": "Boediono",                    "jabatan": "Menteri Keuangan"},
      {"nama": "Hasan Wirajuda",              "jabatan": "Menteri Luar Negeri"},
      {"nama": "Hari Sabarno",                "jabatan": "Menteri Dalam Negeri"},
      {"nama": "Matori Abdul Djalil",         "jabatan": "Menteri Pertahanan"},
      {"nama": "Yusril Ihza Mahendra",        "jabatan": "Menteri Kehakiman dan HAM"},
      {"nama": "Bambang Sudibyo",             "jabatan": "Menteri Pendidikan Nasional"},
      {"nama": "Achmad Sujudi",               "jabatan": "Menteri Kesehatan"},
      {"nama": "Bungaran Saragih",            "jabatan": "Menteri Pertanian"},
      {"nama": "Purnomo Yusgiantoro",         "jabatan": "Menteri Energi dan Sumber Daya Mineral"},
      {"nama": "Soenarso",                    "jabatan": "Menteri Kehutanan"},
      {"nama": "Rini Soewandi",               "jabatan": "Menteri Perindustrian dan Perdagangan"},
      {"nama": "Bachtiar Chamsyah",           "jabatan": "Menteri Sosial"},
      {"nama": "Laksamana Sukardi",           "jabatan": "Menteri BUMN"},
      {"nama": "Said Agil Husin Al-Munawar",  "jabatan": "Menteri Agama"},
      {"nama": "Siti Nurbaya",                "jabatan": "Sekretaris Negara"},
    ],
  },
  # ───────────────────────────── SBY I ────────────────────────────────────────
  {
    "kabinet": "Kabinet Indonesia Bersatu I",
    "presiden": "Susilo Bambang Yudhoyono",
    "periode": "21 Oktober 2004 - 22 Oktober 2009",
    "menteri": [
      {"nama": "Susilo Bambang Yudhoyono",    "jabatan": "Presiden"},
      {"nama": "Jusuf Kalla",                 "jabatan": "Wakil Presiden"},
      {"nama": "Widodo AS",                   "jabatan": "Menko Politik, Hukum, dan Keamanan"},
      {"nama": "Aburizal Bakrie",             "jabatan": "Menko Perekonomian"},
      {"nama": "Alwi Shihab",                 "jabatan": "Menko Kesejahteraan Rakyat"},
      {"nama": "Hassan Wirajuda",             "jabatan": "Menteri Luar Negeri"},
      {"nama": "Mohammad Mahfud",             "jabatan": "Menteri Pertahanan"},
      {"nama": "M. Ma'ruf",                   "jabatan": "Menteri Dalam Negeri"},
      {"nama": "Hamid Awaludin",              "jabatan": "Menteri Hukum dan HAM"},
      {"nama": "Sri Mulyani",                 "jabatan": "Menteri Keuangan"},
      {"nama": "Purnomo Yusgiantoro",         "jabatan": "Menteri Energi dan Sumber Daya Mineral"},
      {"nama": "Andung Nitimihardja",         "jabatan": "Menteri Perindustrian"},
      {"nama": "Mari Elka Pangestu",          "jabatan": "Menteri Perdagangan"},
      {"nama": "Anton Apriyantono",           "jabatan": "Menteri Pertanian"},
      {"nama": "MS Kaban",                    "jabatan": "Menteri Kehutanan"},
      {"nama": "Freddy Numberi",              "jabatan": "Menteri Kelautan dan Perikanan"},
      {"nama": "Hatta Rajasa",                "jabatan": "Menteri Perhubungan"},
      {"nama": "Lukman Edy",                  "jabatan": "Menteri Tenaga Kerja dan Transmigrasi"},
      {"nama": "Joko Kirmanto",               "jabatan": "Menteri Pekerjaan Umum"},
      {"nama": "Muhammad Nuh",                "jabatan": "Menteri Komunikasi dan Informatika"},
      {"nama": "Bambang Sudibyo",             "jabatan": "Menteri Pendidikan Nasional"},
      {"nama": "Siti Fadilah Supari",         "jabatan": "Menteri Kesehatan"},
      {"nama": "Bachtiar Chamsyah",           "jabatan": "Menteri Sosial"},
      {"nama": "Maftuh Basyuni",              "jabatan": "Menteri Agama"},
      {"nama": "Andi Mattalatta",             "jabatan": "Menteri Pemuda dan Olahraga"},
      {"nama": "Sofjan Djalil",               "jabatan": "Menteri BUMN"},
    ],
  },
  # ───────────────────────────── SBY II ───────────────────────────────────────
  {
    "kabinet": "Kabinet Indonesia Bersatu II",
    "presiden": "Susilo Bambang Yudhoyono",
    "periode": "22 Oktober 2009 - 20 Oktober 2014",
    "menteri": [
      {"nama": "Susilo Bambang Yudhoyono",    "jabatan": "Presiden"},
      {"nama": "Boediono",                    "jabatan": "Wakil Presiden"},
      {"nama": "Djoko Suyanto",               "jabatan": "Menko Politik, Hukum, dan Keamanan"},
      {"nama": "Hatta Rajasa",                "jabatan": "Menko Perekonomian"},
      {"nama": "Agung Laksono",               "jabatan": "Menko Kesejahteraan Rakyat"},
      {"nama": "Marty Natalegawa",            "jabatan": "Menteri Luar Negeri"},
      {"nama": "Purnomo Yusgiantoro",         "jabatan": "Menteri Pertahanan"},
      {"nama": "Gamawan Fauzi",               "jabatan": "Menteri Dalam Negeri"},
      {"nama": "Patrialis Akbar",             "jabatan": "Menteri Hukum dan HAM"},
      {"nama": "Sri Mulyani",                 "jabatan": "Menteri Keuangan"},
      {"nama": "Darwin Zahedy Saleh",         "jabatan": "Menteri Energi dan Sumber Daya Mineral"},
      {"nama": "M.S. Hidayat",                "jabatan": "Menteri Perindustrian"},
      {"nama": "Mari Elka Pangestu",          "jabatan": "Menteri Pariwisata dan Ekonomi Kreatif"},
      {"nama": "Gita Wirjawan",               "jabatan": "Menteri Perdagangan"},
      {"nama": "Suswono",                     "jabatan": "Menteri Pertanian"},
      {"nama": "Zulkifli Hasan",              "jabatan": "Menteri Kehutanan"},
      {"nama": "Sharif Cicip Sutardjo",       "jabatan": "Menteri Kelautan dan Perikanan"},
      {"nama": "E.E. Mangindaan",             "jabatan": "Menteri Perhubungan"},
      {"nama": "Muhaimin Iskandar",           "jabatan": "Menteri Tenaga Kerja dan Transmigrasi"},
      {"nama": "Djoko Kirmanto",              "jabatan": "Menteri Pekerjaan Umum"},
      {"nama": "Tifatul Sembiring",           "jabatan": "Menteri Komunikasi dan Informatika"},
      {"nama": "Mohammad Nuh",                "jabatan": "Menteri Pendidikan dan Kebudayaan"},
      {"nama": "Nafsiah Mboi",                "jabatan": "Menteri Kesehatan"},
      {"nama": "Salim Segaf Al-Jufri",        "jabatan": "Menteri Sosial"},
      {"nama": "Suryadharma Ali",             "jabatan": "Menteri Agama"},
      {"nama": "Roy Suryo",                   "jabatan": "Menteri Pemuda dan Olahraga"},
      {"nama": "Dahlan Iskan",                "jabatan": "Menteri BUMN"},
      {"nama": "Chatib Basri",                "jabatan": "Menteri Keuangan (pengganti)"},
      {"nama": "Andrinof Chaniago",           "jabatan": "Kepala Bappenas"},
    ],
  },
  # ───────────────────────────── JOKOWI I ─────────────────────────────────────
  {
    "kabinet": "Kabinet Kerja",
    "presiden": "Joko Widodo",
    "periode": "27 Oktober 2014 - 23 Oktober 2019",
    "menteri": [
      {"nama": "Joko Widodo",                 "jabatan": "Presiden"},
      {"nama": "Jusuf Kalla",                 "jabatan": "Wakil Presiden"},
      {"nama": "Luhut Binsar Pandjaitan",     "jabatan": "Kepala Staf Kepresidenan"},
      {"nama": "Tedjo Edhy Purdijatno",       "jabatan": "Menko Politik, Hukum, dan Keamanan"},
      {"nama": "Sofyan Djalil",               "jabatan": "Menko Perekonomian"},
      {"nama": "Puan Maharani",               "jabatan": "Menko Pembangunan Manusia dan Kebudayaan"},
      {"nama": "Indroyono Soesilo",           "jabatan": "Menko Kemaritiman"},
      {"nama": "Retno Lestari Priansari Marsudi", "jabatan": "Menteri Luar Negeri"},
      {"nama": "Ryamizard Ryacudu",           "jabatan": "Menteri Pertahanan"},
      {"nama": "Tjahjo Kumolo",               "jabatan": "Menteri Dalam Negeri"},
      {"nama": "Yasonna H. Laoly",            "jabatan": "Menteri Hukum dan HAM"},
      {"nama": "Bambang PS Brodjonegoro",     "jabatan": "Menteri Keuangan"},
      {"nama": "Sudirman Said",               "jabatan": "Menteri Energi dan Sumber Daya Mineral"},
      {"nama": "Saleh Husin",                 "jabatan": "Menteri Perindustrian"},
      {"nama": "Rachmat Gobel",               "jabatan": "Menteri Perdagangan"},
      {"nama": "Amran Sulaiman",              "jabatan": "Menteri Pertanian"},
      {"nama": "Siti Nurbaya Bakar",          "jabatan": "Menteri Lingkungan Hidup dan Kehutanan"},
      {"nama": "Susi Pudjiastuti",            "jabatan": "Menteri Kelautan dan Perikanan"},
      {"nama": "Ignasius Jonan",              "jabatan": "Menteri Perhubungan"},
      {"nama": "Hanif Dhakiri",               "jabatan": "Menteri Ketenagakerjaan"},
      {"nama": "Basuki Hadimuljono",          "jabatan": "Menteri Pekerjaan Umum dan Perumahan Rakyat"},
      {"nama": "Rudiantara",                  "jabatan": "Menteri Komunikasi dan Informatika"},
      {"nama": "Anies Baswedan",              "jabatan": "Menteri Pendidikan dan Kebudayaan"},
      {"nama": "Nila Djuwita F. Moeloek",     "jabatan": "Menteri Kesehatan"},
      {"nama": "Khofifah Indar Parawansa",    "jabatan": "Menteri Sosial"},
      {"nama": "Lukman Hakim Saifuddin",      "jabatan": "Menteri Agama"},
      {"nama": "Imam Nahrawi",                "jabatan": "Menteri Pemuda dan Olahraga"},
      {"nama": "Rini Soemarno",               "jabatan": "Menteri BUMN"},
      {"nama": "Yuddy Chrisnandi",            "jabatan": "Menteri Pendayagunaan Aparatur Negara"},
      {"nama": "Ferry Mursyidan Baldan",      "jabatan": "Menteri Agraria dan Tata Ruang"},
      {"nama": "Marwan Jafar",                "jabatan": "Menteri Desa, PDT, dan Transmigrasi"},
      {"nama": "Andrinof Chaniago",           "jabatan": "Menteri PPN/Kepala Bappenas"},
      {"nama": "Yohana Yembise",              "jabatan": "Menteri Pemberdayaan Perempuan dan Perlindungan Anak"},
    ],
  },
  # ───────────────────────────── JOKOWI II ────────────────────────────────────
  {
    "kabinet": "Kabinet Indonesia Maju",
    "presiden": "Joko Widodo",
    "periode": "23 Oktober 2019 - 20 Oktober 2024",
    "menteri": [
      {"nama": "Joko Widodo",                 "jabatan": "Presiden"},
      {"nama": "Ma'ruf Amin",                 "jabatan": "Wakil Presiden"},
      {"nama": "Mahfud MD",                   "jabatan": "Menko Politik, Hukum, dan Keamanan"},
      {"nama": "Airlangga Hartarto",          "jabatan": "Menko Perekonomian"},
      {"nama": "Muhadjir Effendy",            "jabatan": "Menko Pembangunan Manusia dan Kebudayaan"},
      {"nama": "Luhut Binsar Pandjaitan",     "jabatan": "Menko Kemaritiman dan Investasi"},
      {"nama": "Retno Marsudi",               "jabatan": "Menteri Luar Negeri"},
      {"nama": "Prabowo Subianto",            "jabatan": "Menteri Pertahanan"},
      {"nama": "Tito Karnavian",              "jabatan": "Menteri Dalam Negeri"},
      {"nama": "Yasonna H. Laoly",            "jabatan": "Menteri Hukum dan HAM"},
      {"nama": "Sri Mulyani Indrawati",       "jabatan": "Menteri Keuangan"},
      {"nama": "Arifin Tasrif",               "jabatan": "Menteri Energi dan Sumber Daya Mineral"},
      {"nama": "Agus Gumiwang Kartasasmita",  "jabatan": "Menteri Perindustrian"},
      {"nama": "Agus Suparmanto",             "jabatan": "Menteri Perdagangan"},
      {"nama": "Syahrul Yasin Limpo",         "jabatan": "Menteri Pertanian"},
      {"nama": "Siti Nurbaya Bakar",          "jabatan": "Menteri Lingkungan Hidup dan Kehutanan"},
      {"nama": "Edhy Prabowo",                "jabatan": "Menteri Kelautan dan Perikanan"},
      {"nama": "Budi Karya Sumadi",           "jabatan": "Menteri Perhubungan"},
      {"nama": "Ida Fauziyah",                "jabatan": "Menteri Ketenagakerjaan"},
      {"nama": "Basuki Hadimuljono",          "jabatan": "Menteri Pekerjaan Umum dan Perumahan Rakyat"},
      {"nama": "Johnny G. Plate",             "jabatan": "Menteri Komunikasi dan Informatika"},
      {"nama": "Nadiem Anwar Makarim",        "jabatan": "Menteri Pendidikan, Kebudayaan, Riset, dan Teknologi"},
      {"nama": "Budi Gunadi Sadikin",         "jabatan": "Menteri Kesehatan"},
      {"nama": "Tri Rismaharini",             "jabatan": "Menteri Sosial"},
      {"nama": "Yaqut Cholil Qoumas",         "jabatan": "Menteri Agama"},
      {"nama": "Zainudin Amali",              "jabatan": "Menteri Pemuda dan Olahraga"},
      {"nama": "Erick Thohir",                "jabatan": "Menteri BUMN"},
      {"nama": "Tjahjo Kumolo",               "jabatan": "Menteri Pendayagunaan Aparatur Negara dan Reformasi Birokrasi"},
      {"nama": "Sofyan Djalil",               "jabatan": "Menteri Agraria dan Tata Ruang"},
      {"nama": "Abdul Halim Iskandar",        "jabatan": "Menteri Desa, PDT, dan Transmigrasi"},
      {"nama": "Suharso Monoarfa",            "jabatan": "Menteri PPN/Kepala Bappenas"},
      {"nama": "I Gusti Ayu Bintang Darmawati","jabatan": "Menteri Pemberdayaan Perempuan dan Perlindungan Anak"},
      {"nama": "Sandiaga Salahuddin Uno",     "jabatan": "Menteri Pariwisata dan Ekonomi Kreatif"},
      {"nama": "Bahlil Lahadalia",            "jabatan": "Menteri Investasi/Kepala BKPM"},
      {"nama": "Hadi Tjahjanto",              "jabatan": "Menteri Agraria dan Tata Ruang (2023)"},
    ],
  },
  # ───────────────────────────── PRABOWO ──────────────────────────────────────
  {
    "kabinet": "Kabinet Merah Putih",
    "presiden": "Prabowo Subianto",
    "periode": "20 Oktober 2024 - 20 Oktober 2029",
    "menteri": [
      {"nama": "Prabowo Subianto",            "jabatan": "Presiden"},
      {"nama": "Gibran Rakabuming Raka",      "jabatan": "Wakil Presiden"},
      {"nama": "Budi Djiwandono",             "jabatan": "Kepala Badan Intelijen Negara"},
      {"nama": "AM Hendropriyono",            "jabatan": "Penasihat Khusus Presiden"},
      {"nama": "Yusril Ihza Mahendra",        "jabatan": "Menko Hukum, HAM, Imigrasi, dan Pemasyarakatan"},
      {"nama": "Zulkifli Hasan",              "jabatan": "Menko Pangan"},
      {"nama": "Airlangga Hartarto",          "jabatan": "Menko Perekonomian"},
      {"nama": "Agus Harimurti Yudhoyono",    "jabatan": "Menko Infrastruktur dan Pembangunan Kewilayahan"},
      {"nama": "Muhadjir Effendy",            "jabatan": "Menko Pembangunan Manusia dan Kebudayaan"},
      {"nama": "Prasetyo Hadi",               "jabatan": "Menko Politik dan Keamanan"},
      {"nama": "Sugiono",                     "jabatan": "Menteri Luar Negeri"},
      {"nama": "Sjafrie Sjamsoeddin",         "jabatan": "Menteri Pertahanan"},
      {"nama": "Muhammad Tito Karnavian",     "jabatan": "Menteri Dalam Negeri"},
      {"nama": "Supratman Andi Agtas",        "jabatan": "Menteri Hukum"},
      {"nama": "Natalius Pigai",              "jabatan": "Menteri HAM"},
      {"nama": "Sri Mulyani Indrawati",       "jabatan": "Menteri Keuangan"},
      {"nama": "Bahlil Lahadalia",            "jabatan": "Menteri Energi dan Sumber Daya Mineral"},
      {"nama": "Agus Gumiwang Kartasasmita",  "jabatan": "Menteri Perindustrian"},
      {"nama": "Budi Santoso",                "jabatan": "Menteri Perdagangan"},
      {"nama": "Andi Amran Sulaiman",         "jabatan": "Menteri Pertanian"},
      {"nama": "Raja Juli Antoni",            "jabatan": "Menteri Kehutanan"},
      {"nama": "Hanif Faisol Nurofiq",        "jabatan": "Menteri Lingkungan Hidup"},
      {"nama": "Sakti Wahyu Trenggono",       "jabatan": "Menteri Kelautan dan Perikanan"},
      {"nama": "Dudy Purwagandhi",            "jabatan": "Menteri Perhubungan"},
      {"nama": "Yassierli",                   "jabatan": "Menteri Ketenagakerjaan"},
      {"nama": "Dody Hanggodo",               "jabatan": "Menteri Pekerjaan Umum"},
      {"nama": "Maruarar Sirait",             "jabatan": "Menteri Perumahan dan Kawasan Permukiman"},
      {"nama": "Meutya Hafid",                "jabatan": "Menteri Komunikasi dan Digital"},
      {"nama": "Abdul Mu'ti",                 "jabatan": "Menteri Pendidikan Dasar dan Menengah"},
      {"nama": "Satryo Soemantri Brodjonegoro","jabatan": "Menteri Pendidikan Tinggi, Sains, dan Teknologi"},
      {"nama": "Budi Gunadi Sadikin",         "jabatan": "Menteri Kesehatan"},
      {"nama": "Saifullah Yusuf",             "jabatan": "Menteri Sosial"},
      {"nama": "Nasaruddin Umar",             "jabatan": "Menteri Agama"},
      {"nama": "Dito Ariotedjo",              "jabatan": "Menteri Pemuda dan Olahraga"},
      {"nama": "Erick Thohir",                "jabatan": "Menteri BUMN"},
      {"nama": "Rini Widyantini",             "jabatan": "Menteri Pendayagunaan Aparatur Negara dan Reformasi Birokrasi"},
      {"nama": "Nusron Wahid",                "jabatan": "Menteri Agraria dan Tata Ruang"},
      {"nama": "Yandri Susanto",              "jabatan": "Menteri Desa dan Pembangunan Daerah Tertinggal"},
      {"nama": "Muhammad Isa Ansori",         "jabatan": "Menteri Transmigrasi"},
      {"nama": "Rachmat Pambudy",             "jabatan": "Menteri PPN/Kepala Bappenas"},
      {"nama": "Ribka Haluk",                 "jabatan": "Menteri Pemberdayaan Perempuan dan Perlindungan Anak"},
      {"nama": "Teuku Riefky Harsya",         "jabatan": "Menteri Ekonomi Kreatif"},
      {"nama": "Widiyanti Putri Wardhana",    "jabatan": "Menteri Pariwisata"},
      {"nama": "Rosan Roeslani",              "jabatan": "Menteri Investasi dan Hilirisasi"},
      {"nama": "Wahyu Sakti Trenggono",       "jabatan": "Menteri Kelautan dan Perikanan"},
      {"nama": "Fadli Zon",                   "jabatan": "Menteri Kebudayaan"},
      {"nama": "Thomas Djiwandono",           "jabatan": "Wakil Menteri Keuangan"},
      {"nama": "Bambang Susantono",           "jabatan": "Kepala Otorita IKN"},
    ],
  },
]

# ── Output helpers ─────────────────────────────────────────────────────────────

CSV_FIELDS = ["nama", "jabatan", "kabinet", "presiden", "tahun_mulai", "tahun_selesai"]


def save_csv(path: Path, data: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(data)


def save_txt(path: Path, data: list[dict]) -> None:
    lines = [
        "=" * 70,
        "  KABINET & MENTERI REPUBLIK INDONESIA",
        "  Sumber: Wikipedia, Sekretariat Kabinet RI, Setneg",
        f"  Dibuat: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 70,
        f"\nTotal pejabat tercatat: {len(data):,}",
        f"Total kabinet: {len(KABINET_DATA)}",
        "",
    ]

    for k in KABINET_DATA:
        kabinet = k["kabinet"]
        presiden = k["presiden"]
        periode  = k["periode"]
        menteri  = k["menteri"]
        lines += [
            "",
            "=" * 70,
            f"  {kabinet.upper()}",
            f"  Presiden : {presiden}",
            f"  Periode  : {periode}",
            f"  Jumlah   : {len(menteri)} pejabat",
            "-" * 70,
        ]
        for m in menteri:
            jabatan = m["jabatan"]
            nama    = m["nama"]
            lines.append(f"  {jabatan:<50}  {nama}")

    lines += [
        "",
        "=" * 70,
        "File CSV: kabinet_indonesia.csv (buka di Excel/Sheets)",
        "=" * 70,
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def save_json(path: Path) -> None:
    path.write_text(
        json.dumps(KABINET_DATA, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def collect(target_presiden: list[str] | None = None) -> list[dict]:
    rows: list[dict] = []
    filter_p = [p.lower() for p in (target_presiden or [])]

    for k in KABINET_DATA:
        if filter_p and not any(fp in k["presiden"].lower() for fp in filter_p):
            continue
        # Parse periode
        parts = k["periode"].split(" - ")
        tahun_mulai   = parts[0].split()[-1] if parts else ""
        tahun_selesai = parts[1].split()[-1] if len(parts) > 1 else ""

        for m in k["menteri"]:
            rows.append({
                "nama":          m["nama"],
                "jabatan":       m["jabatan"],
                "kabinet":       k["kabinet"],
                "presiden":      k["presiden"],
                "tahun_mulai":   tahun_mulai,
                "tahun_selesai": tahun_selesai,
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Data kabinet & menteri Indonesia 1945-2029"
    )
    parser.add_argument("--presiden", nargs="+", metavar="NAMA",
                        help="Filter presiden. Contoh: --presiden Jokowi Prabowo")
    parser.add_argument("--list", action="store_true",
                        help="Tampilkan daftar kabinet")
    parser.add_argument("--json", action="store_true",
                        help="Simpan juga ke JSON (kabinet_indonesia.json)")
    args = parser.parse_args()

    if args.list:
        print(f"\n{'#':<3} {'Kabinet':<40} {'Presiden':<25} Periode")
        print("-" * 80)
        for i, k in enumerate(KABINET_DATA, 1):
            print(f"{i:<3} {k['kabinet']:<40} {k['presiden']:<25} {k['periode']}")
        return

    rows = collect(target_presiden=args.presiden)
    csv_path  = Path("kabinet_indonesia.csv")
    txt_path  = Path("kabinet_indonesia.txt")
    json_path = Path("kabinet_indonesia.json")

    # Filter KABINET_DATA for txt output if filtering
    filtered_kabinet = KABINET_DATA
    if args.presiden:
        fp = [p.lower() for p in args.presiden]
        filtered_kabinet = [k for k in KABINET_DATA
                            if any(p in k["presiden"].lower() for p in fp)]

    save_csv(csv_path, rows)
    # Temporarily swap for filtered output
    original = KABINET_DATA.copy()
    KABINET_DATA.clear()
    KABINET_DATA.extend(filtered_kabinet)
    save_txt(txt_path, rows)
    KABINET_DATA.clear()
    KABINET_DATA.extend(original)

    if args.json:
        save_json(json_path)
        print(f"JSON disimpan ke {json_path}")

    print(f"\nSELESAI")
    print(f"  Kabinet : {len(filtered_kabinet)}")
    print(f"  Pejabat : {len(rows):,}")
    print(f"  CSV     : {csv_path}")
    print(f"  TXT     : {txt_path}")


if __name__ == "__main__":
    main()
