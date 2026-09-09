"""
agents/image_agent.py — Image analysis, generation, and editing for Hermes.

  analyze_image(image_bytes, question)
      → Describe / answer questions about a photo using Claude vision
        (falls back to Ollama llava if Claude is unavailable).

  generate_image(prompt)
      → Generate a new image from text using fal.ai (Flux.1 Dev by default).
        Requires FAL_KEY in .env.  Model configurable via FAL_T2I_MODEL.

  edit_image(image_bytes, instruction)
      → Understand the uploaded image with vision, then generate a new version
        that incorporates the edit instruction.
"""
from __future__ import annotations

import asyncio
import base64
import logging

import httpx

import config

logger = logging.getLogger(__name__)



ANALYZE_SYSTEM = (
    "You are Hermes, an expert image analyst. "
    "Describe what you see clearly and answer any question about the image. "
    "Be concise but thorough."
)

EDIT_SYSTEM = (
    "You are Hermes, an expert image editor. The user has uploaded an image and wants to modify it.\n"
    "Step 1 — Describe the original image in detail (composition, subjects, colors, style, lighting).\n"
    "Step 2 — Produce a high-quality Flux/Stable-Diffusion prompt that re-creates the image WITH the\n"
    "         requested edit applied (e.g. watermark removed, logo removed, text cleaned, background\n"
    "         changed, etc.). The prompt must be vivid, comma-separated tags, include 8k/photorealistic\n"
    "         quality tags. For watermark/text removal: describe the clean image without any overlaid\n"
    "         text, logos, or watermarks.\n"
    "Format your response EXACTLY as (no extra text outside these two lines):\n"
    "DESCRIPTION: <detailed description of original image>\n"
    "EDIT_PROMPT: <flux prompt for the edited image, applying the user instruction>"
)

# Flux.1 uses natural language — no SD-style booster tags
# This suffix adds cinematic quality cues that work with Flux
_QUALITY_SUFFIX = (
    ", highly detailed, sharp focus, professional photography, 8K resolution"
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _image_to_b64(image_bytes: bytes) -> str:
    return base64.standard_b64encode(image_bytes).decode()


async def _claude_vision(image_bytes: bytes, question: str, system: str, model: str = "") -> str:
    """Send image + question to Claude vision API."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    b64 = _image_to_b64(image_bytes)
    # Detect media type (JPEG / PNG / GIF / WEBP)
    media_type = "image/jpeg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        media_type = "image/png"
    elif image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        media_type = "image/gif"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        media_type = "image/webp"

    response = await client.messages.create(
        model=model or config.ANTHROPIC_VISION_MODEL,
        max_tokens=1024,
        system=system,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64",
                                                  "media_type": media_type,
                                                  "data": b64}},
                    {"type": "text", "text": question or "Describe this image."},
                ],
            }
        ],
    )
    return response.content[0].text


async def _ollama_vision(image_bytes: bytes, question: str) -> str:
    """Send image + question to Ollama llava model."""
    b64 = _image_to_b64(image_bytes)
    payload = {
        "model": config.OLLAMA_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": question or "Describe this image.",
                "images": [b64],
            }
        ],
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
        resp.raise_for_status()
    return resp.json()["message"]["content"]


# ── Public API ─────────────────────────────────────────────────────────────

async def analyze_image(image_bytes: bytes, question: str = "") -> str:
    """
    Analyze an image and return a text description / answer.
    Tries Ollama vision first (privacy), then Claude.
    """
    if config.OLLAMA_VISION_MODEL:
        try:
            return await _ollama_vision(image_bytes, question)
        except Exception as e:
            logger.warning(f"Ollama vision failed ({e}), trying Claude...")

    if config.ANTHROPIC_API_KEY:
        return await _claude_vision(image_bytes, question, ANALYZE_SYSTEM)

    raise RuntimeError("No vision backend available. Set OLLAMA_VISION_MODEL or ANTHROPIC_API_KEY.")


async def generate_image(prompt: str, negative_prompt: str = "") -> bytes:
    """
    Generate an image from a text prompt using fal.ai (Flux.1 Dev by default).
    Model is configurable via FAL_T2I_MODEL in .env.
    Returns raw image bytes (JPEG/PNG).
    Raises RuntimeError when FAL_KEY is not configured.
    """
    if not config.FAL_KEY:
        raise RuntimeError(
            "FAL_KEY is not set. Get a free key at https://fal.ai/dashboard/keys "
            "and add it to your .env file."
        )

    import os
    import fal_client  # type: ignore

    os.environ["FAL_KEY"] = config.FAL_KEY

    # Append quality cues (Flux uses natural language, not SD tags)
    enhanced = prompt + _QUALITY_SUFFIX

    arguments: dict = {
        "prompt": enhanced,
        "image_size": "landscape_4_3",
        "num_inference_steps": 50,
        "guidance_scale": 3.5,
        "num_images": 1,
        "enable_safety_checker": True,
    }
    if negative_prompt.strip():
        arguments["negative_prompt"] = negative_prompt

    logger.info(f"Generating image via fal.ai ({config.FAL_T2I_MODEL}): {prompt[:80]!r}")
    result: dict = await fal_client.subscribe_async(
        config.FAL_T2I_MODEL,
        arguments=arguments,
        with_logs=True,
        on_queue_update=lambda u: logger.info(f"fal.ai t2i: {u}"),
    )

    # fal returns {"images": [{"url": "...", ...}]}
    images = result.get("images") or []
    image_url: str = (images[0].get("url") if images else None) or result.get("image", {}).get("url", "")
    if not image_url:
        raise RuntimeError(f"fal.ai returned no image URL. Full response: {result}")

    logger.info(f"Image ready: {image_url}")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(image_url)
        resp.raise_for_status()
    return resp.content


async def image_to_video(image_bytes: bytes, prompt: str = "", negative_prompt: str = "", duration: int = 5) -> bytes:
    """
    Animate a still image into a short video clip using fal.ai.

    Supported models (set FAL_I2V_MODEL in .env):
      • fal-ai/kling-video/v1.6/standard/image-to-video  (default, 5-10 s)
      • fal-ai/minimax-video/image-to-video
      • fal-ai/wan-i2v

    Returns raw MP4 bytes.
    Raises RuntimeError when FAL_KEY is not configured.
    """
    if not config.FAL_KEY:
        raise RuntimeError(
            "FAL_KEY is not set. Get a free key at https://fal.ai/dashboard/keys "
            "and add it to your .env file."
        )

    import os
    import fal_client  # type: ignore

    # fal_client reads FAL_KEY from the environment
    os.environ["FAL_KEY"] = config.FAL_KEY

    # Step 1: upload image to fal CDN (async)
    image_url: str = await fal_client.upload_async(image_bytes, "image/jpeg")
    logger.info(f"Image uploaded to fal: {image_url}")

    # Step 2: submit i2v job and poll until complete (async)
    arguments: dict = {"image_url": image_url}
    if prompt:
        arguments["prompt"] = prompt
    if negative_prompt.strip():
        arguments["negative_prompt"] = negative_prompt
    # Kling accepts duration as int (5 or 10); other models ignore unknown keys
    arguments["duration"] = duration

    logger.info(f"Submitting i2v job to {config.FAL_I2V_MODEL!r} (prompt={prompt!r}, duration={duration}s) …")
    result: dict = await fal_client.subscribe_async(
        config.FAL_I2V_MODEL,
        arguments=arguments,
        with_logs=True,
        on_queue_update=lambda u: logger.info(f"fal.ai: {u}"),
    )

    # Extract the video URL — fal returns {"video": {"url": "..."}}
    video_url: str = (
        (result.get("video") or {}).get("url")
        or result.get("video_url")
        or result.get("url")
        or ""
    )
    if not video_url:
        raise RuntimeError(f"fal.ai returned no video URL. Full response: {result}")

    logger.info(f"Video ready: {video_url}")

    # Step 3: download video bytes
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(video_url)
        resp.raise_for_status()
    return resp.content


async def edit_image(image_bytes: bytes, instruction: str) -> tuple[bytes, str]:
    """
    Edit an image based on a text instruction.
    1. Vision model analyzes the image and builds an edit prompt.
    2. Pollinations generates a new image from the edit prompt.
    Returns (image_bytes, description).
    """
    # Step 1: vision → edit prompt
    if config.OLLAMA_VISION_MODEL:
        try:
            raw = await _ollama_vision(image_bytes, instruction)
        except Exception as e:
            logger.warning(f"Ollama vision failed for edit ({e}), using Claude...")
            raw = await _claude_vision(image_bytes, instruction, EDIT_SYSTEM)
    elif config.ANTHROPIC_API_KEY:
        raw = await _claude_vision(image_bytes, instruction, EDIT_SYSTEM, model=config.ANTHROPIC_VISION_MODEL)
    else:
        raise RuntimeError("No vision backend available.")

    # Parse EDIT_PROMPT from response
    edit_prompt = instruction  # default fallback
    description = raw
    for line in raw.splitlines():
        if line.upper().startswith("EDIT_PROMPT:"):
            edit_prompt = line.split(":", 1)[1].strip()
        elif line.upper().startswith("DESCRIPTION:"):
            description = line.split(":", 1)[1].strip()

    # Step 2: generate new image
    new_image = await generate_image(edit_prompt)
    return new_image, description
