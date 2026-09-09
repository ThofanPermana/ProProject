"""
tools/build_dataset.py — Fine-tuning dataset builder for Hermes.

Generates a JSONL dataset from:
  1. Conversation history in memory/data/ (real user conversations)
  2. Manual Q&A pairs in tools/qa_pairs.jsonl (curated by you)

Output format: ChatML JSONL compatible with Unsloth / LLaMA-Factory / Ollama fine-tuning.

Usage:
    python tools/build_dataset.py
    python tools/build_dataset.py --min-len 30 --output my_dataset.jsonl

Output file: tools/hermes_dataset.jsonl

Each line:
    {"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import config
from agents.hermes_agent import SYSTEM_PROMPT

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TOOLS_DIR       = Path(__file__).parent
OUTPUT_FILE     = TOOLS_DIR / "hermes_dataset.jsonl"
QA_FILE         = TOOLS_DIR / "qa_pairs.jsonl"
AUTO_DATASET    = TOOLS_DIR / "auto_dataset.jsonl"   # real-time collected data


# ── Helpers ───────────────────────────────────────────────────────────────

def _is_quality(user_msg: str, assistant_msg: str, min_len: int) -> bool:
    """Filter out very short or empty exchanges."""
    if len(user_msg.strip()) < min_len:
        return False
    if len(assistant_msg.strip()) < min_len * 2:
        return False
    # Skip error messages
    if assistant_msg.startswith("Error:") or assistant_msg.startswith("Gagal"):
        return False
    return True


def _load_history_files(min_len: int) -> list[dict]:
    """
    Load all conversation histories from memory/data/.
    Each session file contains a list of {role, content} messages.
    Returns a list of ChatML records.
    """
    records: list[dict] = []
    data_dir = config.MEMORY_DIR

    for hist_file in sorted(data_dir.glob("*_*.json")):
        # Skip index files
        if hist_file.stem.endswith("_idx"):
            continue
        try:
            messages: list[dict] = json.loads(hist_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Skipping {hist_file.name}: {e}")
            continue

        # Extract consecutive user→assistant pairs
        i = 0
        while i < len(messages) - 1:
            msg = messages[i]
            nxt = messages[i + 1]
            if msg.get("role") == "user" and nxt.get("role") == "assistant":
                user_text = msg.get("content", "").strip()
                asst_text = nxt.get("content", "").strip()
                if _is_quality(user_text, asst_text, min_len):
                    records.append({
                        "messages": [
                            {"role": "system",    "content": SYSTEM_PROMPT},
                            {"role": "user",      "content": user_text},
                            {"role": "assistant", "content": asst_text},
                        ]
                    })
                i += 2
            else:
                i += 1

    logger.info(f"Loaded {len(records)} pairs from conversation history")
    return records


def _load_auto_dataset() -> list[dict]:
    """
    Load the real-time auto-collected dataset (auto_dataset.jsonl).
    This is written by dataset_logger.py during live bot operation.
    """
    if not AUTO_DATASET.exists():
        logger.info("No auto_dataset.jsonl found yet — start the bot to collect data.")
        return []

    records: list[dict] = []
    for i, line in enumerate(AUTO_DATASET.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            # Strip _meta before adding to final dataset
            obj.pop("_meta", None)
            if "messages" in obj:
                records.append(obj)
        except json.JSONDecodeError as e:
            logger.warning(f"auto_dataset.jsonl line {i}: {e}")

    logger.info(f"Loaded {len(records)} records from auto_dataset.jsonl")
    return records


def _load_qa_pairs() -> list[dict]:
    """
    Load manually curated Q&A pairs from tools/qa_pairs.jsonl.
    
    Format of qa_pairs.jsonl (one JSON object per line):
        {"user": "Apa itu RAG?", "assistant": "RAG adalah..."}
        or
        {"messages": [...]}   ← already in ChatML format
    """
    if not QA_FILE.exists():
        logger.info(
            f"No qa_pairs.jsonl found at {QA_FILE}. "
            "Create it to add curated training pairs."
        )
        _create_qa_template()
        return []

    records: list[dict] = []
    for i, line in enumerate(QA_FILE.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning(f"qa_pairs.jsonl line {i}: {e}")
            continue

        if "messages" in obj:
            records.append(obj)
        elif "user" in obj and "assistant" in obj:
            records.append({
                "messages": [
                    {"role": "system",    "content": SYSTEM_PROMPT},
                    {"role": "user",      "content": obj["user"].strip()},
                    {"role": "assistant", "content": obj["assistant"].strip()},
                ]
            })
        else:
            logger.warning(f"qa_pairs.jsonl line {i}: unrecognised format, skipping")

    logger.info(f"Loaded {len(records)} pairs from qa_pairs.jsonl")
    return records


def _create_qa_template() -> None:
    """Create a starter qa_pairs.jsonl with examples."""
    examples = [
        {"user": "Siapa kamu?", "assistant": "Saya Hermes, asisten AI yang cerdas dan serbaguna. Saya bisa membantu kamu dengan pertanyaan apa pun, menulis, coding, analisis, dan banyak lagi."},
        {"user": "Apa itu RAG?", "assistant": "RAG (Retrieval-Augmented Generation) adalah teknik yang menggabungkan pencarian dokumen relevan dengan generasi teks oleh LLM. Sebelum menjawab, sistem mencari potongan dokumen yang paling relevan dari knowledge base, lalu menyertakannya sebagai konteks tambahan untuk LLM. Hasilnya jawaban lebih akurat dan berbasis fakta nyata."},
        {"user": "Jelaskan fine-tuning LLM", "assistant": "Fine-tuning adalah proses melatih ulang model bahasa yang sudah pre-trained dengan dataset khusus agar lebih mahir pada domain tertentu. Tahapannya: (1) Siapkan dataset JSONL berisi pasangan instruksi-respons, (2) Gunakan framework seperti Unsloth atau LLaMA-Factory, (3) Latih dengan LoRA/QLoRA agar lebih efisien, (4) Merge adapter ke model dasar, (5) Export ke GGUF untuk digunakan dengan Ollama."},
    ]
    QA_FILE.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in examples) + "\n",
        encoding="utf-8",
    )
    logger.info(f"Created starter qa_pairs.jsonl at {QA_FILE}")


def _deduplicate(records: list[dict]) -> list[dict]:
    """Remove exact duplicate user messages."""
    seen: set[str] = set()
    unique: list[dict] = []
    for rec in records:
        msgs = rec.get("messages", [])
        user_msgs = [m["content"] for m in msgs if m["role"] == "user"]
        key = " ".join(user_msgs)
        if key not in seen:
            seen.add(key)
            unique.append(rec)
    return unique


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Build Hermes fine-tuning dataset")
    parser.add_argument(
        "--min-len", type=int, default=20,
        help="Minimum character length for user message (default: 20)"
    )
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_FILE,
        help=f"Output JSONL path (default: {OUTPUT_FILE})"
    )
    parser.add_argument(
        "--no-history", action="store_true",
        help="Skip conversation history, only use qa_pairs.jsonl"
    )
    args = parser.parse_args()

    records: list[dict] = []

    if not args.no_history:
        records += _load_history_files(args.min_len)

    records += _load_auto_dataset()
    records += _load_qa_pairs()
    records  = _deduplicate(records)

    if not records:
        logger.warning("No records generated. Dataset is empty.")
        return

    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info(f"✅ Dataset saved: {output} ({len(records)} records)")
    print(f"\n{'='*55}")
    print(f"  Dataset: {output}")
    print(f"  Records: {len(records)}")
    print(f"{'='*55}")
    print("\nNext steps for fine-tuning:")
    print("  Option A — Unsloth (Google Colab, free GPU):")
    print("    Upload hermes_dataset.jsonl to Colab")
    print("    Use: unsloth/llama-3.2-3b-instruct-bnb-4bit")
    print("    Train with SFTTrainer, export to GGUF")
    print("    Then: ollama create hermes-ft -f Modelfile")
    print()
    print("  Option B — LLaMA-Factory (local):")
    print("    pip install llamafactory")
    print("    llamafactory-cli train --dataset hermes_dataset.jsonl ...")
    print()
    print("  Option C — Ollama + Modelfile only (no fine-tuning):")
    print("    Add your qa_pairs.jsonl as examples in the Modelfile SYSTEM prompt")


if __name__ == "__main__":
    main()
