"""
Suggesting a lesson title from extracted source text.

The admin should not have to name a lesson before she has even read it. The
composer creates lessons without asking for a title, so one is derived here
and shown in the editor where it can be corrected in place.

Same principle as the corpus importer: rules, not a model call. Naming a
lesson is not worth spending the client's budget on, and a rule is
predictable in a way a generated title is not.
"""

from __future__ import annotations

import re

from app.services.ingestion.base import has_hebrew, hebrew_ratio

MAX_TITLE = 70

LABEL_TRANSLITERATION = re.compile(r"^\s*transliteration\s*[:\-–]\s*", re.IGNORECASE)
LABEL_TRANSLATION = re.compile(r"^\s*translation\s*[:\-–]\s*", re.IGNORECASE)

# "🌸 Insights into Nishmat Kol Chai – Lesson #17" and similar headers.
SERIES_HEADER = re.compile(
    r"^\s*[^\w\s]*\s*(?:insights into\s+)?nishmat(\s+kol\s+chai)?\b.*?(?:lesson|day)?\s*#?\s*\d*\s*$",
    re.IGNORECASE,
)

# Some lessons label the phrase rather than glossing it:
#     "Words: הַגִּבּוֹר לָנֶצַח"
# The label is not the lesson's name — without this, #93 came out titled "Words".
GLOSS_LABEL = re.compile(
    r"^(?:the\s+)?(?:words?|phrase|text|pasuk|verse|tefillah|line)\s*$",
    re.IGNORECASE,
)

GREETING = re.compile(
    r"^\s*(shavua tov|good (morning|evening)|motzaei|welcome|hello|hi\b)",
    re.IGNORECASE,
)

LEADING_EMOJI = re.compile(r"^\s*[\U0001F300-\U0001FAFF☀-➿]+\s*")


def suggest_title(text: str | None, *, fallback: str = "Untitled lesson") -> str:
    """
    Pick a short, human title from extracted source text.

    Preference order mirrors how these lessons are actually headed:
      1. an explicit "Transliteration:" line — the phrase the lesson is about
      2. an explicit "Translation:" line
      3. the Latin gloss beside a Hebrew phrase ("אַתָּה אֵל | Atah Kel")
      4. the first real line that is not a series header or a greeting
    """
    if not text or not text.strip():
        return fallback

    lines = [line.strip() for line in text.splitlines()]
    head = [line for line in lines[:25] if line]

    for line in head:
        if LABEL_TRANSLITERATION.match(line):
            title = _tidy(LABEL_TRANSLITERATION.sub("", line))
            if title:
                return title

    for line in head:
        if LABEL_TRANSLATION.match(line):
            title = _tidy(LABEL_TRANSLATION.sub("", line))
            if title:
                return title

    for line in head:
        if has_hebrew(line):
            gloss = _latin_gloss(line)
            if gloss:
                title = _tidy(gloss)
                if title:
                    return title

    for line in head:
        if SERIES_HEADER.match(line) or GREETING.match(line):
            continue
        if hebrew_ratio(line) > 0.5:
            continue
        title = _tidy(line)
        if title and len(title) >= 8:
            return title

    return fallback


def _latin_gloss(line: str) -> str | None:
    """Pull the non-Hebrew half out of 'הַגָּדוֹל – HaGadol' style lines."""
    for separator in ("–", "—", "|", " - ", ":"):
        if separator not in line:
            continue
        left, _, right = line.partition(separator)

        if has_hebrew(left) and right.strip() and not has_hebrew(right):
            return None if GLOSS_LABEL.match(right.strip()) else right
        if has_hebrew(right) and left.strip() and not has_hebrew(left):
            # Some lessons LABEL the phrase instead of glossing it:
            # "Words: הַגִּבּוֹר לָנֶצַח". The label is not the lesson's name.
            return None if GLOSS_LABEL.match(left.strip()) else left
    return None


def _tidy(text: str) -> str | None:
    text = LEADING_EMOJI.sub("", text).strip().strip("\"“”'’ ,;:-–—")

    # A series header is not a title.
    if SERIES_HEADER.match(text):
        return None
    if not text or len(text) < 3:
        return None

    # Sentences make poor titles — keep the first clause.
    if len(text) > MAX_TITLE:
        clipped = text[:MAX_TITLE].rsplit(" ", 1)[0].rstrip(",;:-–—")
        return f"{clipped}…" if clipped else None

    return text
