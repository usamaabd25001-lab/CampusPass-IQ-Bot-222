from __future__ import annotations

import httpx

from app.core.config import Settings


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def answer(self, question: str, context: str = "") -> str:
        # Availability is controlled by the database feature flag in the support
        # workflow. The client itself only validates that an API key exists.
        if not self.settings.gemini_api_key:
            raise RuntimeError("Gemini is disabled: GEMINI_API_KEY is missing")
        prompt = (
            f"{self.settings.gemini_system_prompt}\n\n"
            f"سياق الخدمة غير الحساس:\n{context[:3000]}\n\n"
            f"سؤال المستخدم:\n{question[:2000]}"
        )
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_model}:generateContent"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 600},
        }
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                url,
                headers={
                    "x-goog-api-key": self.settings.gemini_api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code >= 400:
                detail = ""
                try:
                    payload_error = response.json()
                    detail = str(payload_error.get("error", {}).get("message", ""))[:300]
                except Exception:
                    detail = response.text[:300]
                raise RuntimeError(
                    f"Gemini API error {response.status_code}: {detail or 'unknown error'}"
                )
            data = response.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Gemini returned an unexpected response") from exc
        return text[:3500]
