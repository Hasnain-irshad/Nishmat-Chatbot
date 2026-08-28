"""
The LLM interface.

Everything the application needs from a model provider is declared here, and
nothing else in the codebase imports a vendor SDK. Swapping provider — or
running the whole pipeline against fixtures — is a change to this one seam.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from app.llm.types import Completion, Embeddings, Message, Transcription


@runtime_checkable
class LLMProvider(Protocol):
    """
    `operation` is a short label ("analysis", "generation", "chat", …). It
    selects the configured model for that job and is what makes `ai_usage`
    readable — you can see exactly which stage spent the money.
    """

    name: str

    async def complete(
        self,
        messages: list[Message],
        *,
        operation: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> Completion:
        """
        Generate text. When `json_schema` is supplied the provider must return
        output conforming to it, with the parsed object on `Completion.parsed`.
        """
        ...

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        operation: str = "transcription",
        language: str | None = None,
        prompt: str | None = None,
    ) -> Transcription:
        """
        Speech to text. `prompt` seeds domain vocabulary — for this client that
        is the Hebrew and Yiddish terms the model would otherwise mangle.
        """
        ...

    async def describe_image(
        self,
        image: bytes,
        *,
        mime_type: str,
        instruction: str,
        operation: str = "vision",
    ) -> Completion:
        """Read and describe an image. Not OCR — vision understanding."""
        ...

    async def embed(
        self, texts: list[str], *, operation: str = "embedding"
    ) -> Embeddings:
        ...


FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"


def get_provider() -> LLMProvider:
    """
    The provider for the current mode.

    `LLM_MODE=mock` returns fixtures and costs nothing — this is the default
    while building, so no amount of development can spend the client's budget.
    """
    from app.config import get_settings

    settings = get_settings()

    if settings.llm_mode == "mock":
        from app.llm.mock_provider import MockProvider

        return MockProvider()

    from app.llm.openai_provider import OpenAIProvider

    return OpenAIProvider()
