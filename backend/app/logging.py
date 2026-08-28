"""
Structured logging with secret redaction.

Anything that looks like a key must never reach a log line. Logs get copied
into tickets, pasted into chats, and shipped to third-party services; a leaked
service-role key in a log is a leaked service-role key.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

from app.config import get_settings

# sk-…, sb_secret_…, JWTs, and anything explicitly labelled a key/token.
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sb_(?:secret|publishable)_[A-Za-z0-9_\-]{8,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*[=:]\s*\S+"),
]

_SENSITIVE_KEYS = {
    "authorization", "api_key", "apikey", "openai_api_key", "password",
    "token", "access_token", "refresh_token", "secret",
    "supabase_service_role_key", "supabase_anon_key",
}


def _redact_text(value: str) -> str:
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[redacted]", value)
    return value


def redact_processor(_logger: Any, _name: str, event_dict: dict) -> dict:
    for key, value in list(event_dict.items()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "[redacted]"
        elif isinstance(value, str):
            event_dict[key] = _redact_text(value)
    return event_dict


def configure_logging() -> None:
    settings = get_settings()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.is_production
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
