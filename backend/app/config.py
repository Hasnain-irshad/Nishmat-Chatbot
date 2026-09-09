"""
Application configuration.

Every setting comes from the environment. Nothing is hard-coded, and no
default ever contains a secret — a missing secret must fail loudly at startup
rather than silently falling back to something that half-works.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Runtime ----------------------------------------------------------
    environment: Literal["development", "production"] = "development"
    log_level: str = "INFO"
    api_cors_origins: str = "http://localhost:3000"

    # ---- Supabase ---------------------------------------------------------
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_storage_bucket: str = "source-files"

    # Only needed for projects still on legacy HS256 tokens. Projects with
    # asymmetric (ES256/RS256) signing verify through JWKS and need nothing here.
    supabase_jwt_secret: str | None = None

    # ---- OpenAI -----------------------------------------------------------
    openai_api_key: str | None = None

    openai_model_analysis: str = ""
    openai_model_generation: str = ""
    openai_model_modification: str = ""
    openai_model_quality: str = ""
    openai_model_chat: str = ""
    openai_model_utility: str = ""
    openai_model_vision: str = ""
    openai_model_transcription: str = ""
    openai_model_embedding: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536

    openai_max_retries: int = 3
    openai_timeout_seconds: int = 120

    # Vision gets its own, longer budget. Transcribing a full page of vocalised
    # Hebrew legitimately runs to a few thousand output tokens, which is several
    # times a normal completion — at the shared 120s a photographed page timed
    # out, retried three times, and failed six minutes later having cost three
    # full attempts. Retries are capped tighter for the same reason: a timeout
    # here means the page is slow, and trying it twice more rarely helps.
    openai_vision_timeout_seconds: int = 300
    openai_vision_max_retries: int = 2
    openai_vision_max_tokens: int = 6000

    # ---- Budget guardrails ------------------------------------------------
    # The client's total OpenAI budget is fixed. These are enforced in code.
    llm_mode: Literal["mock", "live"] = "mock"
    ai_spend_cap_usd: float = 8.00
    ai_spend_warn_usd: float = 5.00

    # ---- Uploads ----------------------------------------------------------
    max_upload_mb_document: int = 25
    max_upload_mb_image: int = 10
    max_upload_mb_audio: int = 100

    # ---- Worker -----------------------------------------------------------
    worker_poll_interval_seconds: int = 3
    worker_max_attempts: int = 3
    generation_max_auto_retries: int = 1

    # ---- Retrieval / chat -------------------------------------------------
    rag_top_k: int = 6
    rag_min_score: float = 0.25
    chat_history_window: int = 8
    chat_summary_threshold: int = 16

    # Ceiling on a generated chat answer.
    #
    # Was hard-coded at 800, which silently cut answers off mid-sentence: 73 of
    # the 131 published lessons are longer than 800 tokens, so any question that
    # warranted quoting one at length hit the wall. It is a ceiling, not a
    # target — the prompt asks for a few short paragraphs and cost follows what
    # is actually generated, so raising it costs nothing on a normal answer.
    #
    # A request for a lesson's full text does not use this at all; it is served
    # from the database with no model in the path.
    chat_max_answer_tokens: int = 2000

    # ------------------------------------------------------------------ #

    @field_validator("supabase_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url}/auth/v1"

    def max_upload_bytes(self, kind: str) -> int:
        mapping = {
            "pdf": self.max_upload_mb_document,
            "docx": self.max_upload_mb_document,
            "text": self.max_upload_mb_document,
            "image": self.max_upload_mb_image,
            "audio": self.max_upload_mb_audio,
        }
        return mapping.get(kind, self.max_upload_mb_document) * 1024 * 1024

    def require_openai(self) -> str:
        """
        Fetch the OpenAI key, or explain precisely what is missing.

        Called at the point of use rather than at startup so the whole service
        still runs — and every non-AI feature stays testable — while the key
        is not yet available.
        """
        if not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Set it in backend/.env, or run with "
                "LLM_MODE=mock to use recorded fixtures."
            )
        return self.openai_api_key


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process and cached."""
    return Settings()  # type: ignore[call-arg]
