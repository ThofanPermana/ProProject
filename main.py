"""
 main.py — ProProject entry point.

Usage:
    python main.py

Requirements:
    Copy .env.example → .env and fill in your tokens, then:
    pip install -r requirements.txt
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading

import config  # noqa — triggers .env load and output dir creation
from bot.telegram_bot import build_application

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# Suppress noisy per-request HTTP logs from httpx and telegram internals
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.ExtBot").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _start_email_agent() -> None:
    """Run the email agent in a separate daemon thread with its own event loop."""
    from agents.email_agent import EmailAgent
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    agent = EmailAgent()
    try:
        loop.run_until_complete(agent.run())
    finally:
        loop.close()


_LOCK_FILE = os.path.join(os.path.dirname(__file__), ".hermes.lock")


def _acquire_lock() -> None:
    """Exit immediately if another instance is already running."""
    if os.path.exists(_LOCK_FILE):
        try:
            with open(_LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            # Check if that PID is still alive
            os.kill(old_pid, 0)
            # If we reach here → process is alive
            print(
                f"[ERROR] ProProject sudah berjalan (PID {old_pid}). "
                "Tutup dulu instance lama sebelum menjalankan yang baru.",
                file=sys.stderr,
            )
            sys.exit(1)
        except ProcessLookupError:
            # Process no longer exists — stale lock, safe to continue
            pass
        except PermissionError:
            # Windows: process exists but different session/user → treat as running
            print(
                "[ERROR] ProProject mungkin sudah berjalan di session lain. "
                "Jalankan: taskkill /IM python.exe /F",
                file=sys.stderr,
            )
            sys.exit(1)
        except (ValueError, OSError):
            # Can't parse PID or other OS error → treat as stale
            pass
    with open(_LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))


def _release_lock() -> None:
    try:
        os.remove(_LOCK_FILE)
    except OSError:
        pass


def main() -> None:
    _acquire_lock()
    try:
        _run()
    finally:
        _release_lock()


def _run() -> None:
    logger.info("Starting ProProject...")

    if config.EMAIL_ENABLED:
        t = threading.Thread(target=_start_email_agent, daemon=True, name="email-agent")
        t.start()
        logger.info("Email agent thread started.")

    # Python 3.10+ no longer auto-creates an event loop — set one explicitly
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = build_application(config.TELEGRAM_TOKEN)
    logger.info("Polling for Telegram updates. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
