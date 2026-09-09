"""
agents/data_agent.py — Data Indonesia lookup agent for Hermes.

Provides instant search over embedded datasets:
  • DPR RI 2024-2029 (556 anggota)
  • Kabinet Indonesia (243 pejabat, 9 kabinet)

Usage (internal):
    from agents.data_agent import DataAgent
    agent = DataAgent()
    result = agent.query_dpr("PKS Jawa Barat")
    result = agent.query_kabinet("menteri ESDM Prabowo")
"""
from __future__ import annotations

import json
import re
import sys
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────
_TOOLS_DIR = Path(__file__).parent.parent / "tools"
_DPR_JSON     = _TOOLS_DIR / "dpr_indonesia.json"
_KABINET_JSON = _TOOLS_DIR / "kabinet_indonesia.json"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to load {path}: {e}")
        return None


def _normalize(s: str) -> str:
    """Lowercase + strip diacritics-ish for fuzzy match."""
    s = s.lower()
    for a, b in [("é","e"),("è","e"),("ê","e"),("ā","a"),("ñ","n"),
                 ("ú","u"),("ü","u"),("ó","o"),("'","'"),("'","'")]:
        s = s.replace(a, b)
    return s


class DataAgent:
    """Singleton-friendly data search agent. Thread-safe (read-only after init)."""

    def __init__(self) -> None:
        self._dpr_data:     list[dict] = []
        self._kabinet_data: list[dict] = []
        self._load()

    def _load(self) -> None:
        # DPR
        raw = _load_json(_DPR_JSON)
        if raw and isinstance(raw, dict):
            self._dpr_data = raw.get("anggota", [])
        elif isinstance(raw, list):
            self._dpr_data = raw
        logger.info(f"DataAgent: loaded {len(self._dpr_data)} DPR members")

        # Kabinet
        raw2 = _load_json(_KABINET_JSON)
        if raw2 and isinstance(raw2, dict):
            self._kabinet_data = raw2.get("data", raw2.get("pejabat", []))
        elif isinstance(raw2, list):
            self._kabinet_data = raw2
        logger.info(f"DataAgent: loaded {len(self._kabinet_data)} kabinet records")

    # ── DPR Search ─────────────────────────────────────────────────────────

    def query_dpr(
        self,
        query: str,
        *,
        max_results: int = 25,
    ) -> str:
        """
        Search DPR members by any combination of:
          - Nama anggota
          - Fraksi (PDI-P, Golkar, Gerindra, NasDem, PKB, PKS, PAN, Demokrat)
          - Provinsi / Dapil
          - Komisi (I–XIII)
          - Jabatan (Ketua, Wakil Ketua, Anggota)

        Returns formatted text ready to send to Telegram.
        """
        if not self._dpr_data:
            return "⚠️ Data DPR belum tersedia. Jalankan `dpr_collector.py` terlebih dahulu."

        q = _normalize(query.strip())
        tokens = q.split()

        # Fraksi alias map
        FRAKSI_ALIAS: dict[str, str] = {
            "pdip": "pdi-p", "pdi p": "pdi-p", "pdip": "pdi-p",
            "nasdem": "nasdem", "nas dem": "nasdem",
            "pkb": "pkb", "pks": "pks", "pan": "pan",
            "golkar": "golkar", "demokrat": "demokrat",
            "gerindra": "gerindra",
        }

        # Komisi shorthand
        KOMISI_RE = re.compile(r'\bkomisi\s*([IVXivx]+|\d+)\b', re.I)
        km = KOMISI_RE.search(query)
        komisi_filter = km.group(1).upper() if km else None

        matched: list[dict] = []
        for m in self._dpr_data:
            score = 0
            nm   = _normalize(m.get("nama", ""))
            fr   = _normalize(m.get("fraksi", ""))
            dap  = _normalize(m.get("dapil", ""))
            prov = _normalize(m.get("provinsi", ""))
            kom  = _normalize(m.get("komisi", ""))
            jab  = _normalize(m.get("jabatan", ""))

            # Komisi exact match (from komisi regex)
            if komisi_filter and kom.upper() == komisi_filter:
                score += 3
            elif komisi_filter and kom.upper() != komisi_filter:
                continue  # hard filter if komisi specified

            for tok in tokens:
                # Skip komisi keyword itself
                if tok in ("komisi",):
                    continue
                alias = FRAKSI_ALIAS.get(tok, tok)
                if alias in fr:
                    score += 4
                if tok in nm:
                    score += 5
                if tok in prov or tok in dap:
                    score += 3
                if tok in jab:
                    score += 2

            if score > 0:
                matched.append((score, m))

        if not matched:
            return f"🔍 Tidak ada anggota DPR yang cocok dengan query: *{query}*"

        matched.sort(key=lambda x: -x[0])
        results = [m for _, m in matched[:max_results]]

        return self._format_dpr_results(results, query, len(matched))

    def _format_dpr_results(
        self, rows: list[dict], query: str, total: int
    ) -> str:
        lines = [f"📋 *Anggota DPR RI 2024-2029* — query: _{query}_"]
        if total > len(rows):
            lines.append(f"_(Menampilkan {len(rows)} dari {total} hasil)_")

        # Group by fraksi for readability
        from collections import defaultdict
        by_fraksi: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_fraksi[r.get("fraksi", "?")].append(r)

        for fraksi in sorted(by_fraksi.keys()):
            members = by_fraksi[fraksi]
            lines.append(f"\n*{fraksi}* ({len(members)})")
            for m in members:
                nama   = m.get("nama", "-")
                dapil  = m.get("dapil", "-")
                komisi = m.get("komisi", "-")
                jabatan = m.get("jabatan", "Anggota")
                jab_tag = f" _{jabatan}_" if jabatan != "Anggota" else ""
                lines.append(f"  • {nama} — Dapil {dapil} | Komisi {komisi}{jab_tag}")

        lines.append(
            f"\n_Sumber: Wikipedia ID, data Mei 2026. "
            f"Total embedded: {len(self._dpr_data)} anggota._"
        )
        return "\n".join(lines)

    def get_dpr_fraksi_summary(self) -> str:
        """Return a one-line summary of fraksi composition."""
        if not self._dpr_data:
            return "Data DPR tidak tersedia."
        from collections import Counter
        fc = Counter(m.get("fraksi", "") for m in self._dpr_data)
        parts = [f"{fr}: {n}" for fr, n in sorted(fc.items(), key=lambda x: -x[1])]
        return "Komposisi DPR (2024-2029): " + " | ".join(parts)

    # ── Kabinet Search ──────────────────────────────────────────────────────

    def query_kabinet(
        self,
        query: str,
        *,
        max_results: int = 30,
    ) -> str:
        """
        Search kabinet by:
          - Nama pejabat
          - Jabatan (menteri, wakil menteri, dll)
          - Nama kabinet (Prabowo, Jokowi, dll)
          - Presiden (Soekarno, Soeharto, Habibie, Wahid, Megawati, Yudhoyono, Jokowi, Prabowo)
        """
        if not self._kabinet_data:
            return "⚠️ Data kabinet belum tersedia. Jalankan `kabinet_collector.py`."

        q = _normalize(query.strip())
        tokens = q.split()

        PRESIDEN_ALIAS: dict[str, str] = {
            "jokowi": "jokowi", "joko widodo": "jokowi",
            "prabowo": "prabowo", "sby": "yudhoyono",
            "megawati": "megawati", "mega": "megawati",
            "habibie": "habibie", "wahid": "wahid", "gus dur": "wahid",
            "soeharto": "soeharto", "soekarno": "soekarno",
            "sukarno": "soekarno",
        }

        matched: list[dict] = []
        for m in self._kabinet_data:
            score = 0
            nm  = _normalize(m.get("nama", ""))
            jab = _normalize(m.get("jabatan", ""))
            kab = _normalize(m.get("kabinet", ""))
            prs = _normalize(m.get("presiden", ""))

            for tok in tokens:
                alias = PRESIDEN_ALIAS.get(tok, tok)
                if alias in prs:
                    score += 4
                if tok in nm:
                    score += 5
                if tok in jab:
                    score += 3
                if tok in kab:
                    score += 2

            if score > 0:
                matched.append((score, m))

        if not matched:
            return f"🔍 Tidak ada data kabinet yang cocok: *{query}*"

        matched.sort(key=lambda x: -x[0])
        results = [m for _, m in matched[:max_results]]
        return self._format_kabinet_results(results, query, len(matched))

    def _format_kabinet_results(
        self, rows: list[dict], query: str, total: int
    ) -> str:
        lines = [f"🏛️ *Data Kabinet Indonesia* — query: _{query}_"]
        if total > len(rows):
            lines.append(f"_(Menampilkan {len(rows)} dari {total} hasil)_")

        from collections import defaultdict
        by_kabinet: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_kabinet[r.get("kabinet", "?")].append(r)

        for kab in sorted(by_kabinet.keys()):
            members = by_kabinet[kab]
            prs = members[0].get("presiden", "?")
            thn_mulai = members[0].get("tahun_mulai", "")
            thn_selesai = members[0].get("tahun_selesai", "")
            header = f"\n*{kab}*"
            if thn_mulai:
                header += f" ({thn_mulai}–{thn_selesai or 'kini'})"
            header += f" — Presiden: {prs}"
            lines.append(header)
            for m in members:
                lines.append(f"  • {m.get('nama', '-')} — _{m.get('jabatan', '-')}_")

        lines.append(
            f"\n_Sumber: Data publik Wikipedia/Setneg. "
            f"Total embedded: {len(self._kabinet_data)} pejabat._"
        )
        return "\n".join(lines)

    def get_kabinet_summary(self) -> str:
        """Return current kabinet (Kabinet Merah Putih) pimpinan."""
        current = [
            m for m in self._kabinet_data
            if "prabowo" in _normalize(m.get("presiden", ""))
               or "merah putih" in _normalize(m.get("kabinet", ""))
        ]
        if not current:
            return "Data Kabinet Merah Putih tidak ditemukan."
        from collections import Counter
        lines = [f"*Kabinet Merah Putih (2024–kini)* — {len(current)} pejabat"]
        for m in current[:10]:
            lines.append(f"  • {m['nama']} — {m['jabatan']}")
        if len(current) > 10:
            lines.append(f"  _…dan {len(current)-10} lainnya. Gunakan /kabinet <query> untuk detail._")
        return "\n".join(lines)

    # ── Auto-detect intent ──────────────────────────────────────────────────

    _DPR_KW = {
        "dpr", "anggota dpr", "anggota dewan", "dprd", "fraksi",
        "komisi i", "komisi ii", "komisi iii", "komisi iv", "komisi v",
        "komisi vi", "komisi vii", "komisi viii", "komisi ix", "komisi x",
        "komisi xi", "komisi xii", "komisi xiii",
        "pdi-p", "pdip", "golkar", "gerindra", "nasdem", "pkb", "pks", "pan",
        "demokrat", "anggota parlemen", "legislatif",
        "wakil rakyat", "ketua dpr", "wakil ketua dpr",
    }

    _KABINET_KW = {
        "menteri", "kabinet", "presiden", "wakil presiden", "menko",
        "wakil menteri", "setjen", "kepala badan", "prabowo", "gibran",
        "kabinet merah putih", "kabinet jokowi", "jokowi", "sby",
        "megawati kabinet",
    }

    def detect_intent(self, text: str) -> str | None:
        """
        Returns 'dpr', 'kabinet', or None.
        Called from hermes_agent to decide whether to inject data context.
        """
        tl = _normalize(text)
        if any(kw in tl for kw in self._DPR_KW):
            return "dpr"
        if any(kw in tl for kw in self._KABINET_KW):
            return "kabinet"
        return None

    def build_context(self, text: str) -> str:
        """
        Auto-detect intent and run the appropriate query.
        Returns a context block to inject into LLM system prompt.
        """
        intent = self.detect_intent(text)
        if intent == "dpr":
            result = self.query_dpr(text, max_results=20)
            return f"\n\n## Data DPR RI (dari embedded dataset)\n{result}"
        if intent == "kabinet":
            result = self.query_kabinet(text, max_results=20)
            return f"\n\n## Data Kabinet Indonesia (dari embedded dataset)\n{result}"
        return ""
