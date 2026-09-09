"""
llm/hf_client.py — Hugging Face Transformers inference (local, GPU-accelerated).

Used as the second-priority backend in the LLM chain:
  Ollama → HuggingFace → Claude

The model is loaded once at startup (lazy, on first request).
Runs on CUDA (RTX 2060) if available, otherwise CPU.

Configure via .env:
  HF_MODEL=TinyLlama/TinyLlama-1.1B-Chat-v1.0   (default)
  HF_DEVICE=auto                                   (auto / cpu / cuda)
  HF_MAX_NEW_TOKENS=512
"""
from __future__ import annotations

import asyncio
import logging
from functools import partial

import config

logger = logging.getLogger(__name__)


class HFClient:
    """
    Thin async wrapper around a Hugging Face text-generation pipeline.
    The underlying pipeline is synchronous — we run it in a thread executor
    so it doesn't block the event loop.
    """

    def __init__(self) -> None:
        self._pipe = None          # lazy-loaded on first request
        self._loading = False

    # ── Lazy model loading ────────────────────────────────────────────────

    def _load_pipeline(self) -> None:
        """Blocking — call inside run_in_executor."""
        import torch
        from transformers import pipeline

        device_arg = config.HF_DEVICE  # "auto" / "cpu" / "cuda" / "cuda:0"

        # "auto" → pick CUDA if available
        if device_arg == "auto":
            device_arg = "cuda" if torch.cuda.is_available() else "cpu"

        logger.info(
            f"Loading HuggingFace model '{config.HF_MODEL}' on device='{device_arg}'..."
        )

        self._pipe = pipeline(
            "text-generation",
            model=config.HF_MODEL,
            device=device_arg,
            torch_dtype=torch.float16 if "cuda" in device_arg else torch.float32,
            trust_remote_code=False,
        )
        logger.info(f"HuggingFace model loaded: {config.HF_MODEL}")

    async def _ensure_loaded(self) -> None:
        if self._pipe is not None:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_pipeline)

    # ── Inference ─────────────────────────────────────────────────────────

    def _infer(self, prompt: str) -> str:
        """Blocking inference — run in executor."""
        outputs = self._pipe(
            prompt,
            max_new_tokens=config.HF_MAX_NEW_TOKENS,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
            pad_token_id=self._pipe.tokenizer.eos_token_id,
            return_full_text=False,
        )
        return outputs[0]["generated_text"].strip()

    async def chat(self, messages: list[dict], system: str = "") -> str:
        """
        Format messages into a prompt and run inference.
        Uses the model's chat template if available (e.g. TinyLlama, Mistral),
        otherwise falls back to a plain text format.
        """
        await self._ensure_loaded()

        # Try chat template first
        try:
            all_messages = []
            if system:
                all_messages.append({"role": "system", "content": system})
            all_messages.extend(messages)

            prompt = self._pipe.tokenizer.apply_chat_template(
                all_messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            # Fallback: plain text prompt
            parts = []
            if system:
                parts.append(f"System: {system}\n")
            for msg in messages:
                role = msg.get("role", "user").capitalize()
                parts.append(f"{role}: {msg.get('content', '')}")
            parts.append("Assistant:")
            prompt = "\n".join(parts)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self._infer, prompt))
