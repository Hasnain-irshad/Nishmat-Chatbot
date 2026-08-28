"""
Spend tracking and the budget ceiling.

The client's OpenAI budget is fixed at $10 and will not be topped up, so this
is a hard control, not a dashboard nicety:

  * every call is recorded in `ai_usage` before its result is returned;
  * every call checks the running total *first* and refuses to proceed once the
    cap is reached.

The total is cached briefly. Reading it from the database on every single call
would add a round-trip to every AI operation, and spend cannot jump far in a
few seconds.
"""

from __future__ import annotations

import time

from app.config import get_settings
from app.db import supabase
from app.llm.types import BudgetExceeded, Usage
from app.logging import get_logger

log = get_logger("llm.usage")

_cached_total: float | None = None
_cached_at: float = 0.0
_CACHE_SECONDS = 15.0


async def total_spend(*, refresh: bool = False) -> float:
    """Total USD spent to date."""
    global _cached_total, _cached_at

    if (
        not refresh
        and _cached_total is not None
        and time.monotonic() - _cached_at < _CACHE_SECONDS
    ):
        return _cached_total

    rows = await supabase.service().select("ai_usage", columns="estimated_cost")
    total = sum(float(row.get("estimated_cost") or 0) for row in rows)

    _cached_total = total
    _cached_at = time.monotonic()
    return total


def _bump_cache(amount: float) -> None:
    """Add a just-incurred cost locally so the cap reacts before the cache expires."""
    global _cached_total
    if _cached_total is not None:
        _cached_total += amount


async def assert_within_budget(estimated_cost: float = 0.0) -> None:
    """
    Refuse the call if it would take us past the cap.

    Raises BudgetExceeded — callers should let it propagate. The API turns it
    into a clear message for the admin rather than a generic error.
    """
    settings = get_settings()
    spent = await total_spend()

    if spent + estimated_cost >= settings.ai_spend_cap_usd:
        log.error(
            "budget_exceeded",
            spent=round(spent, 4),
            cap=settings.ai_spend_cap_usd,
            attempted=round(estimated_cost, 4),
        )
        raise BudgetExceeded(
            f"The AI budget limit of ${settings.ai_spend_cap_usd:.2f} has been "
            f"reached (${spent:.2f} spent). Raise AI_SPEND_CAP_USD to continue."
        )

    if spent >= settings.ai_spend_warn_usd:
        log.warning(
            "budget_warning", spent=round(spent, 4), cap=settings.ai_spend_cap_usd
        )


async def record(
    usage: Usage,
    *,
    user_id: str | None = None,
    lesson_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    """
    Persist what a call cost.

    Never allowed to fail the operation it is measuring — losing one usage row
    is much less bad than losing the lesson the admin just generated. A failure
    here is logged loudly because it blinds the budget cap.
    """
    _bump_cache(usage.estimated_cost)

    try:
        await supabase.service().insert(
            "ai_usage",
            {
                "user_id": user_id,
                "operation": usage.operation,
                "model": usage.model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "audio_seconds": usage.audio_seconds,
                "estimated_cost": round(usage.estimated_cost, 6),
                "lesson_id": lesson_id,
                "conversation_id": conversation_id,
            },
            returning=False,
        )
    except Exception:
        log.exception(
            "usage_record_failed",
            operation=usage.operation,
            model=usage.model,
            cost=usage.estimated_cost,
        )
