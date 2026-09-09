"""
agents/email_agent.py — IMAP inbound email monitor for Hermes.

Polls an Outlook/Hotmail (or any IMAP) inbox and forwards new emails
as Telegram notifications to the configured chat_id.

Config (via .env):
    EMAIL_ENABLED          = true
    EMAIL_IMAP_HOST        = imap-mail.outlook.com
    EMAIL_IMAP_PORT        = 993
    EMAIL_USER             = you@outlook.com
    EMAIL_PASSWORD         = your_password_or_app_password
    EMAIL_POLL_INTERVAL    = 60          # seconds between checks
    EMAIL_NOTIFY_CHAT_ID   = 123456789   # Telegram chat_id to notify
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import logging
from email.header import decode_header as _raw_decode
from email.utils import parseaddr

import httpx

import config

logger = logging.getLogger(__name__)

_TG_SEND = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"


# ── Header / body helpers ─────────────────────────────────────────────────

def _decode_str(value: str | None) -> str:
    """Decode an RFC2047-encoded email header value to plain str."""
    if not value:
        return ""
    parts = _raw_decode(value)
    result: list[str] = []
    for part, charset in parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result).strip()


def _get_body(msg: email.message.Message, max_chars: int = 600) -> str:
    """Extract plain-text body from email (first text/plain part)."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                disp = str(part.get("Content-Disposition", ""))
                if "attachment" in disp:
                    continue
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(charset, errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
    return body.strip()[:max_chars]


# ── Telegram sender ───────────────────────────────────────────────────────

async def _notify_telegram(chat_id: str, text: str) -> None:
    """Send plain text message to a Telegram chat."""
    if len(text) > 4096:
        text = text[:4093] + "..."
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(_TG_SEND, json={"chat_id": chat_id, "text": text})
    except Exception as e:
        logger.warning(f"Telegram notify error: {e}")


# ── IMAP fetch (sync, runs in executor) ──────────────────────────────────

def _fetch_unseen(host: str, port: int, user: str, password: str) -> list[dict]:
    """
    Connect to IMAP, fetch UNSEEN messages, mark them SEEN, return list of dicts.
    Runs in a thread executor (blocking imaplib calls).
    """
    results: list[dict] = []
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(user, password)
        mail.select("INBOX")

        _, data = mail.search(None, "UNSEEN")
        ids = (data[0] or b"").split()

        for uid in ids:
            try:
                _, raw = mail.fetch(uid, "(RFC822)")
                if not raw or not raw[0]:
                    continue
                msg = email.message_from_bytes(raw[0][1])

                raw_from = msg.get("From", "")
                _, from_addr = parseaddr(raw_from)
                from_name = _decode_str(raw_from).split("<")[0].strip() or from_addr

                results.append({
                    "from_name": from_name,
                    "from_addr": from_addr,
                    "subject":   _decode_str(msg.get("Subject", "(no subject)")),
                    "date":      msg.get("Date", ""),
                    "body":      _get_body(msg),
                })

                # Mark as SEEN so we don't re-fetch
                mail.store(uid, "+FLAGS", "\\Seen")
            except Exception as e:
                logger.warning(f"Error processing email uid {uid}: {e}")

        mail.logout()
    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP login/connection error: {e}")
    except Exception as e:
        logger.warning(f"IMAP error: {e}")
    return results


# ── Email Agent ───────────────────────────────────────────────────────────

class EmailAgent:
    """Background IMAP polling agent. Start with await agent.run()."""

    def __init__(self) -> None:
        self.host     = config.EMAIL_IMAP_HOST
        self.port     = config.EMAIL_IMAP_PORT
        self.user     = config.EMAIL_USER
        self.password = config.EMAIL_PASSWORD
        self.interval = config.EMAIL_POLL_INTERVAL
        self.chat_id  = config.EMAIL_NOTIFY_CHAT_ID
        self._running = False

    async def run(self) -> None:
        if not (self.user and self.password and self.chat_id):
            logger.info(
                "Email agent disabled — set EMAIL_USER, EMAIL_PASSWORD, "
                "EMAIL_NOTIFY_CHAT_ID in .env to enable."
            )
            return

        logger.info(
            f"Email agent started: monitoring {self.user} "
            f"via {self.host}:{self.port} every {self.interval}s"
        )
        self._running = True

        while self._running:
            try:
                loop = asyncio.get_event_loop()
                emails = await loop.run_in_executor(
                    None,
                    _fetch_unseen,
                    self.host, self.port, self.user, self.password,
                )
                for em in emails:
                    body_preview = em["body"] or "(tidak ada isi)"
                    text = (
                        f"📧 Email Masuk\n"
                        f"{'─' * 30}\n"
                        f"Dari   : {em['from_name']} <{em['from_addr']}>\n"
                        f"Subjek : {em['subject']}\n"
                        f"Tanggal: {em['date']}\n"
                        f"{'─' * 30}\n"
                        f"{body_preview}"
                    )
                    await _notify_telegram(self.chat_id, text)
                    logger.info(
                        f"Email forwarded to Telegram — "
                        f"from={em['from_addr']!r} subject={em['subject']!r}"
                    )
            except Exception as e:
                logger.warning(f"Email agent loop error: {e}")

            await asyncio.sleep(self.interval)

    def stop(self) -> None:
        self._running = False
