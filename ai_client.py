"""Async Claude API wrapper with batching, concurrency control, and structured output."""
import asyncio
import json
import time
from anthropic import AsyncAnthropic

from config import LLM_API_KEY, LLM_MODEL_FAST, LLM_MODEL_DEEP, LLM_MAX_CONCURRENT


class LLMClient:
    def __init__(self, model: str | None = None, max_concurrent: int | None = None):
        if not LLM_API_KEY:
            raise ValueError("LLM_API_KEY not set. Add it to .env file.")
        self.client = AsyncAnthropic(api_key=LLM_API_KEY)
        self.model = model or LLM_MODEL_FAST
        self.semaphore = asyncio.Semaphore(max_concurrent or LLM_MAX_CONCURRENT)
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        """Single text completion with retry."""
        async with self.semaphore:
            for attempt in range(3):
                try:
                    resp = await self.client.messages.create(
                        model=self.model,
                        max_tokens=max_tokens,
                        system=system,
                        messages=[{"role": "user", "content": user}],
                    )
                    self.total_input_tokens += resp.usage.input_tokens
                    self.total_output_tokens += resp.usage.output_tokens
                    return resp.content[0].text
                except Exception as e:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(2 ** attempt)

    async def complete_json(self, system: str, user: str, max_tokens: int = 4096) -> dict | list:
        """Completion that returns parsed JSON. Instructs Claude to return JSON directly."""
        json_system = system + "\n\nIMPORTANT: Return ONLY valid JSON. No markdown, no code fences, no explanation."
        raw = await self.complete(json_system, user, max_tokens)

        # Strip any markdown fences if Claude adds them
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        return json.loads(text)

    async def batch_complete_json(
        self, requests: list[dict], max_tokens: int = 4096
    ) -> list[dict | list]:
        """Run N completions concurrently. Each request has 'system' and 'user' keys."""
        tasks = [
            self.complete_json(r["system"], r["user"], max_tokens)
            for r in requests
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)


def get_fast_client() -> LLMClient:
    return LLMClient(model=LLM_MODEL_FAST)


def get_deep_client() -> LLMClient:
    return LLMClient(model=LLM_MODEL_DEEP)
