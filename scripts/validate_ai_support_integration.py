from __future__ import annotations

"""Offline validation for the Gemini integration.

No real API key, network call, Telegram call, or database connection is used.
"""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.ai.gemini import (
    GeminiClient,
    GeminiPermanentError,
    GeminiTemporaryError,
)


def settings(**overrides):
    values = {
        "feature_gemini": True,
        "gemini_api_key": "test-api-key-not-real",
        "gemini_model": "gemini-3.6-flash",
        "gemini_system_prompt": "",
        "gemini_timeout_seconds": 5,
        "gemini_retry_attempts": 3,
        "gemini_max_output_tokens": 256,
        "gemini_max_question_chars": 2000,
        "gemini_max_context_chars": 6000,
        "gemini_max_answer_chars": 3500,
        "gemini_temperature": 0.2,
        "ai_concurrency_limit": 2,
        "gemini_cache_ttl_seconds": 300,
        "gemini_cache_max_entries": 20,
        "gemini_circuit_failure_threshold": 2,
        "gemini_circuit_reset_seconds": 10,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def validate_retry_payload_and_cache() -> None:
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "0.01"})
        body = json.loads(request.content.decode("utf-8"))
        assert "systemInstruction" in body
        prompt = body["contents"][0]["parts"][0]["text"]
        assert "<trusted_context>" in prompt
        assert "<user_question>" in prompt
        assert "سؤال المستخدم غير الموثوق" in prompt
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "إجابة اختبار آمنة"}]}}
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GeminiClient(settings(), client=http)
        answer = await client.answer("ما حالة طلبي؟", {"order": {"status": "pending"}})
        assert answer == "إجابة اختبار آمنة"
        assert len(calls) == 2, "429 must be retried once"
        cached = await client.answer("ما حالة طلبي؟", {"order": {"status": "pending"}})
        assert cached == answer
        assert len(calls) == 2, "second identical call must use bounded cache"


async def validate_permanent_failure() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, json={"error": {"message": "secret details"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GeminiClient(settings(), client=http)
        try:
            await client.answer("سؤال صالح", {})
        except GeminiPermanentError as exc:
            assert "secret details" not in str(exc)
        else:
            raise AssertionError("403 must be permanent")
        assert calls == 1, "permanent failures must not retry"


async def validate_circuit_breaker() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    cfg = settings(
        gemini_retry_attempts=1,
        gemini_circuit_failure_threshold=1,
        gemini_cache_ttl_seconds=0,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GeminiClient(cfg, client=http)
        try:
            await client.answer("السؤال الأول", {})
        except GeminiTemporaryError:
            pass
        else:
            raise AssertionError("503 must fail temporarily")
        try:
            await client.answer("السؤال الثاني", {})
        except GeminiTemporaryError as exc:
            assert "circuit" in str(exc).lower()
        else:
            raise AssertionError("open circuit must reject immediately")
        assert calls == 1, "open circuit must prevent a second upstream call"


async def main() -> None:
    await validate_retry_payload_and_cache()
    await validate_permanent_failure()
    await validate_circuit_breaker()
    print("AI support integration validation passed")


if __name__ == "__main__":
    asyncio.run(main())
