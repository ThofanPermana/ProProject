"""
llm/client.py — Unified async LLM client.

Priority:
  1. Groq (cloud, free tier)      — tried first every request
  2. Claude (Anthropic)           — fallback if Groq fails
  3. Ollama (local, GPU)          — last resort if both cloud APIs fail

Set GROQ_API_KEY in .env for Groq tier.
Set ANTHROPIC_API_KEY in .env for Claude tier.
Set OLLAMA_URL in .env (leave empty to disable Ollama / free GPU).
"""
from __future__ import annotations

import logging

import httpx

import config
from llm.hf_client import HFClient

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        self._groq_enabled = bool(config.GROQ_API_KEY)
        self._claude_enabled = bool(config.ANTHROPIC_API_KEY)
        self._ollama_enabled = bool(config.OLLAMA_URL)
        self._hf_enabled = bool(config.HF_MODEL)

        # Default: Claude first if available, else Groq
        self.preferred: str = "claude" if self._claude_enabled else "groq"

        self._hf = HFClient() if self._hf_enabled else None

        if self._groq_enabled:
            from groq import AsyncGroq
            self._groq = AsyncGroq(api_key=config.GROQ_API_KEY)
        else:
            self._groq = None

        if self._claude_enabled:
            import anthropic
            self._claude = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        else:
            self._claude = None

        logger.info(
            f"LLM priority: Groq ({config.GROQ_MODEL}) → "
            f"Claude ({'enabled' if self._claude_enabled else 'disabled'}) → "
            f"Ollama ({'enabled' if self._ollama_enabled else 'disabled'})"
        )

    def set_preferred(self, backend: str) -> bool:
        """Switch preferred backend. Returns True if backend is available."""
        backend = backend.lower()
        if backend == "groq" and self._groq_enabled:
            self.preferred = "groq"
            return True
        if backend in ("claude", "anthropic") and self._claude_enabled:
            self.preferred = "claude"
            return True
        if backend == "ollama" and self._ollama_enabled:
            self.preferred = "ollama"
            return True
        return False

    def _backend_order(self) -> list[str]:
        """Return [preferred, ...rest] filtered to enabled backends."""
        full = ["groq", "claude", "ollama"]
        ordered = [self.preferred] + [b for b in full if b != self.preferred]
        return [b for b in ordered if getattr(self, f"_{b}_enabled", False)]

    @property
    def backend_name(self) -> str:
        label = {"groq": f"Groq ({config.GROQ_MODEL})", "claude": f"Claude ({config.ANTHROPIC_MODEL})", "ollama": f"Ollama ({config.OLLAMA_MODEL})"}
        order = self._backend_order()
        if not order:
            return "no backend"
        parts = [f"{label[order[0]]} [primary]"]
        for b in order[1:]:
            parts.append(f"{label[b]} [fallback]")
        return " → ".join(parts)

    async def chat(self, messages: list[dict], system: str = "") -> str:
        """Try backends in preferred order, falling back on errors."""
        order = self._backend_order()
        for backend in order:
            try:
                if backend == "groq":
                    return await self._chat_groq(messages, system)
                elif backend == "claude":
                    return await self._chat_claude(messages, system)
                elif backend == "ollama":
                    return await self._chat_ollama(messages, system)
            except Exception as e:
                next_b = order[order.index(backend) + 1] if order.index(backend) + 1 < len(order) else None
                if next_b:
                    logger.warning(f"{backend} failed ({e}), trying {next_b}...")
                else:
                    logger.warning(f"{backend} failed ({e}), no more backends...")

        if self._hf_enabled:
            return await self._hf.chat(messages, system)

        raise RuntimeError(
            "No LLM backend available. "
            "Set GROQ_API_KEY, ANTHROPIC_API_KEY, or OLLAMA_URL in .env."
        )

    # ── Groq (cloud, async, primary) ─────────────────────────────────────────

    async def _chat_groq(self, messages: list[dict], system: str) -> str:
        import asyncio as _asyncio
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        response = await _asyncio.wait_for(
            self._groq.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=msgs,
                max_tokens=4096,
            ),
            timeout=60.0,
        )
        logger.info("Groq responded OK")
        return response.choices[0].message.content

    # ── Ollama (local, async) ─────────────────────────────────────────────

    async def _chat_ollama(self, messages: list[dict], system: str) -> str:
        payload: dict = {
            "model": config.OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",  # keep model warm in VRAM for 30 minutes
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=10.0)) as client:
            resp = await client.post(f"{config.OLLAMA_URL}/api/chat", json=payload)
            resp.raise_for_status()
        return resp.json()["message"]["content"]

    # ── Claude (Anthropic, async fallback) ────────────────────────────────

    async def _chat_claude(self, messages: list[dict], system: str) -> str:
        import asyncio as _asyncio
        kwargs: dict = {
            "model": config.ANTHROPIC_MODEL,
            "max_tokens": 4096,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        for attempt in range(4):  # up to 4 tries for 529/500 transient errors
            try:
                response = await _asyncio.wait_for(
                    self._claude.messages.create(**kwargs),
                    timeout=120.0,
                )
                logger.info("Claude responded OK")
                return response.content[0].text
            except _asyncio.TimeoutError:
                raise RuntimeError("Claude API timeout (120s)")
            except Exception as e:
                status = getattr(e, "status_code", None)
                if status in (529, 500, 503) and attempt < 3:
                    wait = 5 * (attempt + 1)  # 5s, 10s, 15s
                    logger.warning(f"Claude {status} (attempt {attempt+1}/4), retrying in {wait}s...")
                    await _asyncio.sleep(wait)
                else:
                    raise
