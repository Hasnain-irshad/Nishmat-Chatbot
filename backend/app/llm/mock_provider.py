"""
Fixture-backed provider.

Two jobs:

  1. Let the entire pipeline — extraction, analysis, generation, quality
     checks, chat — be built and tested without spending anything. The client's
     budget is $10 and fixed; development must not touch it.
  2. Make tests deterministic. A test that asserts on real model output is a
     test that fails for reasons unrelated to the code.

Responses come from `tests/fixtures/llm/` when a matching file exists, and are
otherwise synthesised deterministically from the request. The synthetic path
matters: it means a new pipeline stage works immediately, without someone
first hand-writing a fixture for it.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.llm.provider import FIXTURE_DIR
from app.llm.types import Completion, Embeddings, Message, Transcription, Usage


class MockProvider:
    name = "mock"

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _fingerprint(operation: str, payload: str) -> str:
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"{operation}-{digest}"

    @staticmethod
    def _load_fixture(name: str) -> Any | None:
        path = FIXTURE_DIR / f"{name}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    @staticmethod
    def _usage(operation: str) -> Usage:
        # Zero cost, explicitly. Mock runs must never move the spend total.
        return Usage(model="mock", operation=operation, estimated_cost=0.0)

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
        joined = "\n".join(m.content for m in messages)
        name = self._fingerprint(operation, joined)

        fixture = self._load_fixture(name) or self._load_fixture(operation)
        if fixture is not None:
            text = fixture if isinstance(fixture, str) else json.dumps(fixture)
            parsed = fixture if isinstance(fixture, dict) else None
            return Completion(text=text, parsed=parsed, usage=self._usage(operation))

        if json_schema is not None:
            parsed = _synthesise_from_schema(json_schema)
            return Completion(
                text=json.dumps(parsed, ensure_ascii=False),
                parsed=parsed,
                usage=self._usage(operation),
            )

        return Completion(
            text=(
                f"[mock:{operation}] This is placeholder text produced without "
                f"calling any model. Set LLM_MODE=live to generate real output."
            ),
            usage=self._usage(operation),
        )

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        operation: str = "transcription",
        language: str | None = None,
        prompt: str | None = None,
    ) -> Transcription:
        fixture = self._load_fixture(f"transcription-{filename}") or self._load_fixture(
            "transcription"
        )
        if isinstance(fixture, dict):
            return Transcription(
                text=fixture.get("text", ""),
                language=fixture.get("language"),
                duration_seconds=float(fixture.get("duration_seconds", 0)),
                segments=fixture.get("segments", []),
                usage=self._usage(operation),
            )

        return Transcription(
            text=(
                f"[mock transcription of {filename}] "
                "Shavua tov, beautiful neshamot. This placeholder stands in for "
                "the real transcript. Set LLM_MODE=live to transcribe."
            ),
            language=language or "en",
            duration_seconds=0.0,
            usage=self._usage(operation),
        )

    async def describe_image(
        self,
        image: bytes,
        *,
        mime_type: str,
        instruction: str,
        operation: str = "vision",
    ) -> Completion:
        fixture = self._load_fixture("vision")
        if isinstance(fixture, str):
            return Completion(text=fixture, usage=self._usage(operation))

        return Completion(
            text=(
                "[mock vision] Placeholder description of the uploaded image. "
                "Set LLM_MODE=live to read images."
            ),
            usage=self._usage(operation),
        )

    async def embed(
        self, texts: list[str], *, operation: str = "embedding"
    ) -> Embeddings:
        """
        Deterministic pseudo-embeddings.

        Derived from a hash of the text, so identical input always yields an
        identical vector and near-duplicate text does NOT come out similar.
        That is the honest behaviour: mock retrieval must not look like it
        works, or we would ship believing RAG was tested when it was not.
        """
        from app.config import get_settings

        dimensions = get_settings().openai_embedding_dimensions
        vectors: list[list[float]] = []

        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            # Stretch the digest to the required width.
            raw = (digest * (dimensions // len(digest) + 1))[:dimensions]
            vector = [(byte - 127.5) / 127.5 for byte in raw]
            norm = sum(v * v for v in vector) ** 0.5 or 1.0
            vectors.append([v / norm for v in vector])

        return Embeddings(vectors=vectors, usage=self._usage(operation))


# ------------------------------------------------------------------ schema


def _synthesise_from_schema(schema: dict[str, Any]) -> dict:
    """Build a minimal object satisfying a JSON schema, so parsing succeeds."""
    return _value_for(schema.get("schema", schema))


def _value_for(node: dict[str, Any]) -> Any:
    node_type = node.get("type")

    if node_type == "object":
        properties = node.get("properties", {})
        required = node.get("required", list(properties.keys()))
        return {key: _value_for(properties[key]) for key in required if key in properties}

    if node_type == "array":
        return []
    if node_type == "string":
        enum = node.get("enum")
        return enum[0] if enum else "[mock]"
    if node_type == "integer":
        return 0
    if node_type == "number":
        return 0.0
    if node_type == "boolean":
        return False

    if "anyOf" in node:
        for option in node["anyOf"]:
            if option.get("type") != "null":
                return _value_for(option)
    return None
