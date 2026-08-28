"""Shared types for the LLM layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant"]


@dataclass
class Message:
    role: Role
    content: str


@dataclass
class Usage:
    """What one call consumed. Written to `ai_usage` so spend is always visible."""

    model: str
    operation: str
    input_tokens: int = 0
    output_tokens: int = 0
    audio_seconds: float = 0.0
    estimated_cost: float = 0.0


@dataclass
class Completion:
    text: str
    usage: Usage
    parsed: dict[str, Any] | None = None
    """Set when the call requested a JSON schema — already validated."""


@dataclass
class Transcription:
    text: str
    usage: Usage
    language: str | None = None
    duration_seconds: float = 0.0
    segments: list[dict] = field(default_factory=list)


@dataclass
class Embeddings:
    vectors: list[list[float]]
    usage: Usage


class LLMError(Exception):
    """A provider call failed in a way the caller should handle."""


class BudgetExceeded(LLMError):
    """
    The configured spend cap has been reached.

    Deliberately a hard stop rather than a warning: the client's budget is
    fixed at $10, and a runaway loop could burn it in minutes.
    """
