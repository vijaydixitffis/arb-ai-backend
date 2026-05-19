"""
Asyncio semaphore wrapper for parallel domain node concurrency control.

A single DomainRateLimiter instance is created in LangGraphARBOrchestrator.__init__
and injected into domain nodes via closure. This caps the number of domain agents
that call the LLM simultaneously, protecting provider rate limits (e.g. Gemini 15 RPM).

Usage in a domain node:
    async with rate_limiter:
        result = await domain_agent.validate_domain(...)
"""

from __future__ import annotations

import asyncio


class DomainRateLimiter:
    """Asyncio semaphore shared across all parallel domain agent nodes."""

    def __init__(self, max_parallel: int) -> None:
        self._sem = asyncio.Semaphore(max(1, max_parallel))
        self.max_parallel = max_parallel

    async def __aenter__(self) -> "DomainRateLimiter":
        await self._sem.acquire()
        return self

    async def __aexit__(self, *_) -> None:
        self._sem.release()
