"""
Shared test configuration.

The critical rule: **tests never call a paid API.** LLM_MODE is forced to
"mock" for the whole session regardless of what backend/.env says, so a
developer switching the app to live mode cannot accidentally make the test
suite spend the client's fixed budget.

Tests that genuinely need live behaviour must opt in explicitly and be marked
`@pytest.mark.live`.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def force_mock_llm() -> None:
    """Pin the provider to fixtures before any app module reads settings."""
    os.environ["LLM_MODE"] = "mock"

    # Settings are cached with lru_cache, so clear anything already built.
    from app.config import get_settings

    get_settings.cache_clear()
    assert get_settings().llm_mode == "mock", "tests must never run against live"
    yield
    get_settings.cache_clear()
