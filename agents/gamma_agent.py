"""
agents/gamma_agent.py — Generate a presentation via the Gamma.app public API.

Flow:
  1. POST /v1.0/generations (format=presentation, exportAs=pdf)  → generationId
  2. Poll GET /v1.0/generations/{id} until status == "completed"
  3. Download the PDF export → output/
  4. POST a second generation with exportAs=pptx                  → generationId
  5. Poll + download PPTX → output/
  6. Return {gamma_url, pdf_path, pptx_path, credits_remaining}

If GAMMA_API_KEY is empty, raise RuntimeError immediately.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path

import httpx

import config

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://public-api.gamma.app"
POLL_INTERVAL = 5    # seconds between status checks
MAX_WAIT = 300       # maximum total wait time per generation (seconds)


def _headers() -> dict:
    if not config.GAMMA_API_KEY:
        raise RuntimeError("GAMMA_API_KEY is not set. Add it to your .env file.")
    return {
        "X-API-KEY": config.GAMMA_API_KEY,
        "Content-Type": "application/json",
    }


async def _request_generation(client: httpx.AsyncClient, input_text: str, export_as: str) -> str:
    """Submit a generation request and return the generationId."""
    num_cards = min(4 + input_text.count("##") + 2, 16)
    resp = await client.post(
        f"{GAMMA_API_BASE}/v1.0/generations",
        headers=_headers(),
        json={
            "inputText": input_text,
            "textMode": "generate",
            "format": "presentation",
            "numCards": num_cards,
            "exportAs": export_as,
        },
    )
    resp.raise_for_status()
    gen_id: str = resp.json()["generationId"]
    logger.info(f"Gamma: generationId={gen_id} (exportAs={export_as})")
    return gen_id


async def _poll_until_done(client: httpx.AsyncClient, gen_id: str) -> dict:
    """Poll until status == 'completed' or 'error', return the completed payload."""
    for attempt in range(MAX_WAIT // POLL_INTERVAL):
        await asyncio.sleep(POLL_INTERVAL)
        poll = await client.get(
            f"{GAMMA_API_BASE}/v1.0/generations/{gen_id}",
            headers={"X-API-KEY": config.GAMMA_API_KEY},
        )
        poll.raise_for_status()
        data = poll.json()
        status = data.get("status", "")
        logger.info(f"Gamma: [{attempt * POLL_INTERVAL}s] gen={gen_id} status={status}")
        if status == "completed":
            return data
        if status == "error":
            raise RuntimeError(f"Gamma generation error: {data}")
    raise RuntimeError(f"Gamma timeout after {MAX_WAIT}s for gen_id={gen_id}")


async def _download_file(url: str, dest: Path) -> None:
    """Download a URL to dest path."""
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as dl:
        resp = await dl.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        logger.info(f"Gamma: saved {dest} ({len(resp.content) // 1024} KB)")


def _slug(text: str) -> str:
    return re.sub(r"[^\w]", "_", text.lower())[:40]


async def generate_gamma(topic_text: str) -> dict:
    """
    Generate a Gamma presentation from topic_text.

    Returns:
        {
            "gamma_url":          str,
            "pdf_path":           str | None,
            "pptx_path":          str | None,
            "credits_remaining":  int | str,
        }
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slug(topic_text[:60])
    output_dir = config.OUTPUT_DIR

    gamma_url = ""
    credits_rem: int | str = "?"
    pdf_path: str | None = None
    pptx_path: str | None = None

    async with httpx.AsyncClient(timeout=30) as client:
        # ── Generate PDF ───────────────────────────────────────────────────
        gen_id_pdf = await _request_generation(client, topic_text, "pdf")
        data_pdf = await _poll_until_done(client, gen_id_pdf)

        gamma_url = data_pdf.get("gammaUrl", "")
        export_url_pdf = data_pdf.get("exportUrl", "")
        credits_rem = data_pdf.get("credits", {}).get("remaining", "?")

        if export_url_pdf:
            dest_pdf = output_dir / f"{slug}_{timestamp}.pdf"
            try:
                await _download_file(export_url_pdf, dest_pdf)
                pdf_path = str(dest_pdf)
            except Exception as e:
                logger.warning(f"Gamma PDF download failed: {e}")

        # ── Generate PPTX ─────────────────────────────────────────────────
        try:
            gen_id_pptx = await _request_generation(client, topic_text, "pptx")
            data_pptx = await _poll_until_done(client, gen_id_pptx)
            export_url_pptx = data_pptx.get("exportUrl", "")
            credits_rem = data_pptx.get("credits", {}).get("remaining", credits_rem)

            if export_url_pptx:
                dest_pptx = output_dir / f"{slug}_{timestamp}.pptx"
                await _download_file(export_url_pptx, dest_pptx)
                pptx_path = str(dest_pptx)
        except Exception as e:
            logger.warning(f"Gamma PPTX generation failed (PDF still available): {e}")

    return {
        "gamma_url": gamma_url,
        "pdf_path": pdf_path,
        "pptx_path": pptx_path,
        "credits_remaining": credits_rem,
    }
