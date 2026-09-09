"""
tools/inject_knowledge.py — Load knowledge documents into Hermes' global RAG.

Knowledge injected here is available to ALL users automatically.
Run this script once (or after adding new knowledge files).

Usage:
    python tools/inject_knowledge.py
    python tools/inject_knowledge.py --dir tools/knowledge
    python tools/inject_knowledge.py --clear   # clear global RAG first
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa — triggers .env load
from agents.rag_agent import RAGAgent, GLOBAL_USER_ID


KNOWLEDGE_DIR = ROOT / "tools" / "knowledge"

SUPPORTED_EXTENSIONS = {".txt", ".md", ".rst"}


async def inject_file(rag: RAGAgent, filepath: Path) -> bool:
    """Load a single file into global RAG. Returns True on success."""
    try:
        text = filepath.read_text(encoding="utf-8")
        if len(text.strip()) < 50:
            print(f"  [SKIP] {filepath.name} — too short")
            return False

        doc_id = await rag.add_document(GLOBAL_USER_ID, filepath.name, text)
        print(f"  [OK]   {filepath.name} → doc_id={doc_id}")
        return True
    except Exception as e:
        print(f"  [ERR]  {filepath.name} → {e}")
        return False


async def main(knowledge_dir: Path, clear_first: bool) -> None:
    rag = RAGAgent()

    if clear_first:
        count = rag.clear(GLOBAL_USER_ID)
        print(f"Cleared {count} existing global knowledge documents.\n")

    # List existing global knowledge
    existing = rag.list_documents(GLOBAL_USER_ID)
    if existing and not clear_first:
        print(f"Existing global knowledge ({len(existing)} docs):")
        for doc in existing:
            print(f"  • {doc['filename']} ({doc['chunks']} chunks, added {doc['added_at']})")
        print()

    # Find files to inject
    if not knowledge_dir.exists():
        print(f"Knowledge directory not found: {knowledge_dir}")
        print("Create the directory and add .txt or .md files to teach Hermes.")
        return

    files = [f for f in knowledge_dir.iterdir()
             if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS]

    if not files:
        print(f"No supported files found in {knowledge_dir}")
        print(f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}")
        return

    print(f"Found {len(files)} knowledge file(s) in {knowledge_dir}:")
    ok = 0
    for f in sorted(files):
        result = await inject_file(rag, f)
        if result:
            ok += 1

    print(f"\nDone! {ok}/{len(files)} files injected into global RAG.")

    # Show final stats
    docs = rag.list_documents(GLOBAL_USER_ID)
    total_chunks = sum(d.get("chunks", 0) for d in docs)
    print(f"Global knowledge base: {len(docs)} documents, ~{total_chunks} chunks")
    print("\nHermes will now use this knowledge for ALL users automatically.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject knowledge into Hermes global RAG")
    parser.add_argument("--dir", type=Path, default=KNOWLEDGE_DIR,
                        help=f"Directory containing knowledge files (default: {KNOWLEDGE_DIR})")
    parser.add_argument("--clear", action="store_true",
                        help="Clear existing global knowledge before injecting")
    args = parser.parse_args()

    asyncio.run(main(args.dir, args.clear))
