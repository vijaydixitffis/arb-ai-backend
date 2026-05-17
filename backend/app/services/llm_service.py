"""
Unified LLM Service supporting OpenAI and Gemini.

Key guarantees:
- Gemini: uses system_instruction (separate field) + response_mime_type=application/json
- OpenAI: uses response_format=json_object
- Both: parse_json_from_llm() strips any stray markdown fences before JSON.parse
"""

import json
import logging
import re
import asyncio
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db_config import db_config
from openai import AsyncOpenAI, RateLimitError
from google import genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class LLMService:
    """Unified LLM service — OpenAI, Gemini, or OpenRouter.

    Provider and model are resolved at *call time* from system_config (DB),
    falling back to .env / Settings defaults so that admin UI changes take
    effect immediately without a process restart.

    All provider clients are initialised eagerly so any provider can be
    activated at runtime without restarting the server.
    """

    def __init__(self):
        # Startup provider (used only when no DB session is available)
        self.provider = settings.LLM_PROVIDER.lower()

        # Initialise all clients whose keys are present so switching providers
        # at runtime doesn't require a restart.
        self.gemini_client: Optional[genai.Client] = None
        self.openai_client: Optional[AsyncOpenAI] = None
        self.openrouter_client: Optional[AsyncOpenAI] = None
        self._has_gemini_fallback = False

        if settings.GEMINI_API_KEY:
            self.gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)

        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "your_openai_api_key_here":
            self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        if settings.OPENROUTER_API_KEY:
            self.openrouter_client = AsyncOpenAI(
                api_key=settings.OPENROUTER_API_KEY,
                base_url=OPENROUTER_BASE_URL,
            )
            self._has_gemini_fallback = self.gemini_client is not None

    def _resolve_provider(self, db: Optional[Session]) -> str:
        """Return the effective provider, reading from DB when available."""
        raw = db_config(db, "llm.provider", settings.LLM_PROVIDER) if db else settings.LLM_PROVIDER
        return str(raw).lower()

    # ── Public API ────────────────────────────────────────────────────────────

    async def generate_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        timeout: int = 120,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Generate a JSON-mode completion via the configured LLM provider.

        Pass *db* to resolve provider and model names from system_config at
        call time (admin UI changes take effect without a restart).
        """
        provider = self._resolve_provider(db)
        logger.info(
            f"[LLM] generate_completion provider={provider} "
            f"prompt_len={len(prompt)} system_len={len(system_prompt or '')}"
        )
        try:
            if provider == "openai":
                coro = self._openai_completion(prompt, system_prompt, temperature, max_tokens, db)
            elif provider == "gemini":
                coro = self._gemini_completion(prompt, system_prompt, temperature, max_tokens, db)
            elif provider == "openrouter":
                coro = self._openrouter_completion(prompt, system_prompt, temperature, max_tokens, db)
            else:
                raise ValueError(f"Unsupported LLM provider: {provider}")

            result = await asyncio.wait_for(coro, timeout=timeout)
            logger.info(f"[LLM] OK tokens_used={result.get('tokens_used', 0)}")
            return result

        except asyncio.TimeoutError:
            raise RuntimeError(f"LLM request timed out after {timeout}s")
        except RateLimitError:
            if provider == "openrouter" and self._has_gemini_fallback:
                logger.warning(
                    f"[LLM] OpenRouter 429 rate-limit — falling back to Gemini "
                    f"(model={db_config(db, 'llm.gemini_model', settings.GEMINI_MODEL)})"
                )
                try:
                    result = await asyncio.wait_for(
                        self._gemini_completion(prompt, system_prompt, temperature, max_tokens, db),
                        timeout=timeout,
                    )
                    logger.info(f"[LLM] Gemini fallback OK tokens_used={result.get('tokens_used', 0)}")
                    return result
                except Exception:
                    logger.exception("[LLM] Gemini fallback also failed")
                    raise
            logger.exception("[LLM] generate_completion failed")
            raise
        except Exception:
            logger.exception("[LLM] generate_completion failed")
            raise

    @staticmethod
    def parse_json_from_llm(raw: str) -> Any:
        """Strip markdown code fences then parse JSON.
        Falls back to json_repair for truncated/malformed responses.
        """
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
        cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            try:
                from json_repair import repair_json
                return json.loads(repair_json(cleaned))
            except Exception:
                raise
    
    
    async def generate_embedding(self, text: str) -> list:
        if self.provider == "openai":
            return await self._openai_embedding(text)
        elif self.provider == "openrouter":
            # OpenRouter doesn't expose embeddings — fall back to Gemini if available
            return await self._gemini_embedding(text)
        return await self._gemini_embedding(text)

    # ── OpenAI ────────────────────────────────────────────────────────────────

    async def _openai_completion(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        model = str(db_config(db, "llm.openai_model", settings.OPENAI_MODEL))
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self.openai_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return {
            "content": response.choices[0].message.content,
            "tokens_used": response.usage.total_tokens if response.usage else 0,
            "model": model,
            "provider": "openai",
        }

    async def _openai_embedding(self, text: str) -> list:
        response = await self.openai_client.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding

    # ── OpenRouter ────────────────────────────────────────────────────────────

    async def _openrouter_completion(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Call OpenRouter (OpenAI-compatible) using the configured model."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        model = str(db_config(db, "llm.openrouter_model", settings.OPENROUTER_MODEL))
        logger.info(f"[LLM-OPENROUTER] calling model={model}")

        response = await self.openrouter_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            # JSON mode — not all OpenRouter models support response_format,
            # but Gemma/Llama variants generally do.
            response_format={"type": "json_object"},
            extra_headers={
                "HTTP-Referer": "https://arb-ai-agent.app",
                "X-Title": "ARB AI Agent",
            },
        )
        content = response.choices[0].message.content
        if not content:
            finish_reason = response.choices[0].finish_reason
            raise ValueError(
                f"OpenRouter returned null/empty content (model={model}, "
                f"finish_reason={finish_reason}, tokens={response.usage.total_tokens if response.usage else 0})"
            )
        return {
            "content": content,
            "tokens_used": response.usage.total_tokens if response.usage else 0,
            "model": model,
            "provider": "openrouter",
        }

    # ── Gemini ────────────────────────────────────────────────────────────────

    async def _gemini_completion(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Call Gemini with system_instruction separate from user content,
        and response_mime_type='application/json' to force structured output."""

        model = str(db_config(db, "llm.gemini_model", settings.GEMINI_MODEL))
        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            system_instruction=system_prompt or "",
        )

        logger.info(f"[LLM-GEMINI] calling model={model}")
        response = await self.gemini_client.aio.models.generate_content(
            model=model,
            contents=prompt,   # user content only — system goes in config
            config=config,
        )

        # Guard against safety blocks or empty candidates
        candidate = (response.candidates or [None])[0]
        if candidate is None:
            block_reason = getattr(response.prompt_feedback, "block_reason", "unknown")
            raise RuntimeError(f"Gemini returned no candidates (blockReason={block_reason})")
        if getattr(candidate, "finish_reason", None) == "SAFETY":
            raise RuntimeError("Gemini response blocked by safety filters")

        # Handle multi-part responses (thought_signature, etc.)
        if candidate and hasattr(candidate, 'content') and candidate.content:
            # Extract only text parts, ignore thought_signature and other metadata
            text_parts = [part.text for part in candidate.content.parts if hasattr(part, 'text')]
            content = ''.join(text_parts)
        else:
            # Fallback to response.text for backward compatibility
            content = response.text
            
        if not content:
            raise ValueError("Gemini response has no content")

        tokens_used = 0
        if response.usage_metadata:
            tokens_used = response.usage_metadata.total_token_count or 0

        return {
            "content": content,
            "tokens_used": tokens_used,
            "model": model,
            "provider": "gemini",
        }

    async def _gemini_embedding(self, text: str) -> list:
        response = await self.gemini_client.aio.models.embed_content(
            model=settings.GEMINI_EMBEDDING_MODEL,
            contents=text,
        )
        return response.embeddings[0].values


# Module-level singleton
llm_service = LLMService()
