"""
Cost estimation.

⚠ These rates are from training knowledge and WILL drift. Verify them against
the client's own OpenAI billing page before the first real run, and re-check
after the first live call — `scripts/check_pricing.py` prints what we charged
ourselves so it can be compared against the invoice.

Any model we do not recognise is priced pessimistically rather than at zero.
Estimating an unknown model as free is how a budget cap silently stops working.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rate:
    """USD per 1,000,000 tokens (or per minute, for audio)."""

    input_per_m: float = 0.0
    output_per_m: float = 0.0
    per_minute: float = 0.0


# Chat / completion models
CHAT_RATES: dict[str, Rate] = {
    "gpt-4o": Rate(2.50, 10.00),
    "gpt-4o-mini": Rate(0.15, 0.60),
    "gpt-4.1": Rate(2.00, 8.00),
    "gpt-4.1-mini": Rate(0.40, 1.60),
    "gpt-4.1-nano": Rate(0.10, 0.40),
}

EMBEDDING_RATES: dict[str, Rate] = {
    "text-embedding-3-small": Rate(input_per_m=0.02),
    "text-embedding-3-large": Rate(input_per_m=0.13),
}

AUDIO_RATES: dict[str, Rate] = {
    "whisper-1": Rate(per_minute=0.006),
    "gpt-4o-transcribe": Rate(per_minute=0.006),
    "gpt-4o-mini-transcribe": Rate(per_minute=0.003),
}

# Used when a model is not in any table. Priced at the most expensive tier we
# know of, so an unrecognised model trips the budget cap early rather than late.
UNKNOWN_CHAT_RATE = Rate(3.00, 12.00)
UNKNOWN_AUDIO_RATE = Rate(per_minute=0.010)


def _lookup(model: str, table: dict[str, Rate]) -> Rate | None:
    if model in table:
        return table[model]

    # Providers append dated suffixes: "gpt-4.1-mini-2025-04-14".
    #
    # Match the LONGEST prefix, not the first one found. "gpt-4.1" is a prefix
    # of "gpt-4.1-mini-2025-04-14", so first-match would price a mini model at
    # the full model's rate — five times too high, which would trip the budget
    # cap long before the money was actually spent.
    matches = [known for known in table if model.startswith(known)]
    if matches:
        return table[max(matches, key=len)]
    return None


def chat_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rate = _lookup(model, CHAT_RATES) or UNKNOWN_CHAT_RATE
    return (input_tokens * rate.input_per_m + output_tokens * rate.output_per_m) / 1_000_000


def embedding_cost(model: str, input_tokens: int) -> float:
    rate = _lookup(model, EMBEDDING_RATES) or Rate(input_per_m=0.13)
    return input_tokens * rate.input_per_m / 1_000_000


def audio_cost(model: str, seconds: float) -> float:
    rate = _lookup(model, AUDIO_RATES) or UNKNOWN_AUDIO_RATE
    return (seconds / 60.0) * rate.per_minute


def is_known(model: str) -> bool:
    return any(
        _lookup(model, table) is not None
        for table in (CHAT_RATES, EMBEDDING_RATES, AUDIO_RATES)
    )
