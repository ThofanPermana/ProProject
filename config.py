"""
config.py — Load .env and expose all runtime constants.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (same directory as this file)
load_dotenv(Path(__file__).parent / ".env")

# ── Telegram ───────────────────────────────────────────────────────────────
TELEGRAM_TOKEN: str = os.environ["TELEGRAM_TOKEN"]

# ── LLM ───────────────────────────────────────────────────────────────────
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
# Separate model for vision/image editing — use Opus for best quality
ANTHROPIC_VISION_MODEL: str = os.getenv("ANTHROPIC_VISION_MODEL", "claude-opus-4-5-20251101")

OLLAMA_URL: str = os.getenv("OLLAMA_URL", "")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")

# ── HuggingFace Transformers ───────────────────────────────────────────────
HF_MODEL: str = os.getenv("HF_MODEL", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")
HF_DEVICE: str = os.getenv("HF_DEVICE", "auto")   # auto / cpu / cuda
HF_MAX_NEW_TOKENS: int = int(os.getenv("HF_MAX_NEW_TOKENS", "512"))

# ── Vision / Image ─────────────────────────────────────────────────────────
# Ollama vision model (e.g. llava, bakllava). Leave empty to skip Ollama vision.
OLLAMA_VISION_MODEL: str = os.getenv("OLLAMA_VISION_MODEL", "llava")

# ── Gamma ──────────────────────────────────────────────────────────────────
GAMMA_API_KEY: str = os.getenv("GAMMA_API_KEY", "")

# ── fal.ai (text-to-image & image-to-video) ──────────────────────────────────
FAL_KEY: str = os.getenv("FAL_KEY", "")
FAL_T2I_MODEL: str = os.getenv("FAL_T2I_MODEL", "fal-ai/flux/dev")
FAL_I2V_MODEL: str = os.getenv("FAL_I2V_MODEL", "fal-ai/kling-video/v1.6/standard/image-to-video")

# ── Threat Intel / Recon API Keys (optional) ─────────────────────────────
SECURITYTRAILS_API_KEY: str = os.getenv("SECURITYTRAILS_API_KEY", "")
VIRUSTOTAL_API_KEY:     str = os.getenv("VIRUSTOTAL_API_KEY", "")
GPTZERO_API_KEY:        str = os.getenv("GPTZERO_API_KEY", "")

# ── Web Search ──────────────────────────────────────────────
BRAVE_API_KEY: str = os.getenv("BRAVE_API_KEY", "")
EXA_API_KEY:   str = os.getenv("EXA_API_KEY", "")

# ── Telegram network ─────────────────────────────────────────────────────
# Optional HTTP/SOCKS proxy for Telegram API (e.g. socks5://127.0.0.1:1080)
TELEGRAM_PROXY: str = os.getenv("TELEGRAM_PROXY", "")
# Timeout in seconds for Telegram API connect/read (default 30)
TELEGRAM_CONNECT_TIMEOUT: float = float(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "30"))
TELEGRAM_READ_TIMEOUT: float    = float(os.getenv("TELEGRAM_READ_TIMEOUT",    "30"))

# ── Email (IMAP Inbound Monitor) ─────────────────────────────────────────
EMAIL_ENABLED:         bool = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_IMAP_HOST:       str  = os.getenv("EMAIL_IMAP_HOST", "imap-mail.outlook.com")
EMAIL_IMAP_PORT:       int  = int(os.getenv("EMAIL_IMAP_PORT", "993"))
EMAIL_USER:            str  = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD:        str  = os.getenv("EMAIL_PASSWORD", "")
EMAIL_POLL_INTERVAL:   int  = int(os.getenv("EMAIL_POLL_INTERVAL", "60"))
EMAIL_NOTIFY_CHAT_ID:  str  = os.getenv("EMAIL_NOTIFY_CHAT_ID", "")

# ── Memory ──────────────────────────────────────────────────────────
MAX_HISTORY: int = int(os.getenv("MAX_HISTORY", "40"))

# ── Paths ─────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
MEMORY_DIR = BASE_DIR / "memory" / "data"
OUTPUT_DIR = BASE_DIR / "output"
RAG_DIR    = BASE_DIR / "memory" / "rag"

for _d in [MEMORY_DIR, OUTPUT_DIR, RAG_DIR]:
    _d.mkdir(parents=True, exist_ok=True)
