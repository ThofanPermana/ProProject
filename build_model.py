"""
build_model.py — Build the custom 'hermes' Ollama model from Modelfile.

Usage:
    python build_model.py

What it does:
    1. Checks Ollama is running
    2. Runs: ollama create hermes -f Modelfile
    3. Verifies the model exists
    4. Prints next steps
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import httpx

OLLAMA_EXE = r"C:\Users\Thofa\AppData\Local\Programs\Ollama\ollama.exe"
MODELFILE = Path(__file__).parent / "Modelfile"
MODEL_NAME = "hermes"


def check_ollama_running() -> bool:
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def model_exists(name: str) -> bool:
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=5)
        models = r.json().get("models", [])
        return any(m["name"].startswith(name) for m in models)
    except Exception:
        return False


def main() -> None:
    print("=" * 50)
    print("  Hermes Model Builder")
    print("=" * 50)

    # 1. Check Ollama
    print("\n[1/3] Checking Ollama...")
    if not check_ollama_running():
        print("  ERROR: Ollama is not running.")
        print("  Start it first: ollama serve")
        sys.exit(1)
    print("  OK — Ollama is running")

    # 2. Check Modelfile
    if not MODELFILE.exists():
        print(f"  ERROR: Modelfile not found at {MODELFILE}")
        sys.exit(1)

    # 3. Build model
    print(f"\n[2/3] Building '{MODEL_NAME}' model from Modelfile...")
    print("  This may take 30-60 seconds...\n")

    result = subprocess.run(
        [OLLAMA_EXE, "create", MODEL_NAME, "-f", str(MODELFILE)],
        capture_output=False,  # show output live
    )

    if result.returncode != 0:
        print(f"\n  ERROR: Build failed (exit code {result.returncode})")
        sys.exit(1)

    # 4. Verify
    print(f"\n[3/3] Verifying '{MODEL_NAME}' model...")
    if model_exists(MODEL_NAME):
        print(f"  OK — '{MODEL_NAME}' model is ready!")
    else:
        print("  WARNING: Model may not have been created correctly.")

    print("\n" + "=" * 50)
    print("  DONE! Next steps:")
    print(f"  1. Your .env already has OLLAMA_MODEL={MODEL_NAME}")
    print(f"  2. Restart the bot: python main.py")
    print(f"  3. Test it: ollama run {MODEL_NAME}")
    print("=" * 50)


if __name__ == "__main__":
    main()
