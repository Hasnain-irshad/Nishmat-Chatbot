"""
OpenAI provider.

Built directly on httpx rather than the SDK: the surface we need is small, it
avoids another dependency, and it keeps timeouts, retries and — most
importantly — the budget check under our own control on every call.

Every method follows the same shape:

    check the budget  ->  call  ->  price it  ->  record it  ->  return

The budget check comes first, so an exhausted budget costs nothing at all.
"""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import httpx

from app.config import get_settings
from app.llm import pricing, usage as usage_tracker
from app.llm.types import (
    Completion,
    Embeddings,
    LLMError,
    Message,
    Transcription,
    Usage,
)
from app.logging import get_logger

log = get_logger("llm.openai")

API_BASE = "https://api.openai.com/v1"

# Retried with backoff. Anything else is a caller error and is not retried.
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        self.settings = get_settings()

    # ------------------------------------------------------------ plumbing

    def _model_for(self, operation: str) -> str:
        settings = self.settings
        mapping = {
            "analysis": settings.openai_model_analysis,
            "generation": settings.openai_model_generation,
            "modification": settings.openai_model_modification,
            "quality": settings.openai_model_quality,
            "chat": settings.openai_model_chat,
            "utility": settings.openai_model_utility,
            "vision": settings.openai_model_vision,
            "transcription": settings.openai_model_transcription,
            "embedding": settings.openai_model_embedding,
        }
        model = mapping.get(operation, "")
        if not model:
            raise LLMError(
                f"No model configured for '{operation}'. "
                f"Set OPENAI_MODEL_{operation.upper()} in backend/.env."
            )
        return model

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.require_openai()}",
            "Content-Type": "application/json",
        }

    async def _post(
        self,
        path: str,
        *,
        json_body: dict | None = None,
        files: dict | None = None,
        data: dict | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
    ) -> dict:
        last_error = "unknown error"
        timeout = timeout or self.settings.openai_timeout_seconds
        max_retries = max_retries or self.settings.openai_max_retries

        for attempt in range(max_retries):
            headers = self._headers()
            if files is not None:
                # httpx sets the multipart boundary itself.
                headers.pop("Content-Type", None)

            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{API_BASE}{path}",
                        headers=headers,
                        json=json_body,
                        files=files,
                        data=data,
                    )
            except httpx.HTTPError as exc:
                # httpx timeout exceptions stringify to "", which reached the
                # admin as "network error: " and said nothing about what went
                # wrong. Name the class when the message is empty.
                detail = str(exc) or type(exc).__name__
                last_error = f"network error: {detail} (after {timeout}s)"
            else:
                if response.status_code < 400:
                    return response.json()

                detail = _error_message(response)
                if response.status_code not in RETRY_STATUS:
                    # 401/403/400 will fail identically on retry.
                    raise LLMError(detail)
                last_error = detail

            if attempt < max_retries - 1:
                await asyncio.sleep(1.5 * (2**attempt))

        raise LLMError(f"OpenAI request failed after retries: {last_error}")

    # ------------------------------------------------------------ interface

    async def complete(
        self,
        messages: list[Message],
        *,
        operation: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> Completion:
        model = self._model_for(operation)

        # Rough pre-check so an already-exhausted budget costs nothing.
        estimated = pricing.chat_cost(
            model,
            sum(len(m.content) for m in messages) // 4,
            max_tokens or 1000,
        )
        await usage_tracker.assert_within_budget(estimated)

        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        if json_schema:
            # Structured Outputs: the model is constrained to the schema, so we
            # never have to defend against unparseable JSON downstream.
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": json_schema,
            }

        payload = await self._post("/chat/completions", json_body=body)

        choice = (payload.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""

        parsed = None
        if json_schema:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise LLMError(
                    "The model returned malformed JSON despite a schema"
                ) from exc

        usage = _usage_from(payload, model, operation)
        await usage_tracker.record(usage)
        return Completion(text=text, parsed=parsed, usage=usage)

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        operation: str = "transcription",
        language: str | None = None,
        prompt: str | None = None,
    ) -> Transcription:
        model = self._model_for(operation)

        # Priced per minute, so estimate from size. WhatsApp voice notes run
        # around 19 kbps; this is deliberately generous.
        estimated_seconds = len(audio) / 2500
        await usage_tracker.assert_within_budget(
            pricing.audio_cost(model, estimated_seconds)
        )

        data: dict[str, str] = {"model": model, "response_format": "verbose_json"}
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt

        payload = await self._post(
            "/audio/transcriptions",
            files={"file": (filename, audio)},
            data=data,
        )

        duration = float(payload.get("duration") or estimated_seconds)
        usage = Usage(
            model=model,
            operation=operation,
            audio_seconds=duration,
            estimated_cost=pricing.audio_cost(model, duration),
        )
        await usage_tracker.record(usage)

        return Transcription(
            text=payload.get("text", ""),
            language=payload.get("language"),
            duration_seconds=duration,
            segments=payload.get("segments") or [],
            usage=usage,
        )

    async def describe_image(
        self,
        image: bytes,
        *,
        mime_type: str,
        instruction: str,
        operation: str = "vision",
    ) -> Completion:
        model = self._model_for(operation)
        await usage_tracker.assert_within_budget(pricing.chat_cost(model, 1500, 800))

        encoded = base64.b64encode(image).decode("ascii")
        body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
            "temperature": 0.2,
            # Bounded so a page the model cannot make sense of cannot run on
            # indefinitely against a per-request timeout.
            "max_tokens": self.settings.openai_vision_max_tokens,
        }

        payload = await self._post(
            "/chat/completions",
            json_body=body,
            timeout=self.settings.openai_vision_timeout_seconds,
            max_retries=self.settings.openai_vision_max_retries,
        )
        text = ((payload.get("choices") or [{}])[0].get("message") or {}).get(
            "content"
        ) or ""

        usage = _usage_from(payload, model, operation)
        await usage_tracker.record(usage)
        return Completion(text=text, usage=usage)

    async def embed(
        self, texts: list[str], *, operation: str = "embedding"
    ) -> Embeddings:
        model = self._model_for(operation)
        approx_tokens = sum(len(t) for t in texts) // 4
        await usage_tracker.assert_within_budget(
            pricing.embedding_cost(model, approx_tokens)
        )

        payload = await self._post(
            "/embeddings",
            json_body={
                "model": model,
                "input": texts,
                "dimensions": self.settings.openai_embedding_dimensions,
            },
        )

        vectors = [item["embedding"] for item in payload.get("data", [])]
        input_tokens = (payload.get("usage") or {}).get("prompt_tokens", approx_tokens)

        usage = Usage(
            model=model,
            operation=operation,
            input_tokens=input_tokens,
            estimated_cost=pricing.embedding_cost(model, input_tokens),
        )
        await usage_tracker.record(usage)
        return Embeddings(vectors=vectors, usage=usage)


# ------------------------------------------------------------------ helpers


def _usage_from(payload: dict, model: str, operation: str) -> Usage:
    raw = payload.get("usage") or {}
    input_tokens = raw.get("prompt_tokens", 0)
    output_tokens = raw.get("completion_tokens", 0)
    return Usage(
        model=model,
        operation=operation,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=pricing.chat_cost(model, input_tokens, output_tokens),
    )


def _error_message(response: httpx.Response) -> str:
    """OpenAI's own message, without ever echoing the request (it holds the key)."""
    try:
        body = response.json()
        message = (body.get("error") or {}).get("message")
        if message:
            return f"OpenAI {response.status_code}: {message}"
    except ValueError:
        pass
    return f"OpenAI {response.status_code}"
