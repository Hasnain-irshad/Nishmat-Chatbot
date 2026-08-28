"""
Checking a finished lesson against the material it was given.

This runs in code, not in a model, and that is the point. The existing quality
stage asks a model "did this lesson invent anything?", which works well for
tone and structure but is exactly the wrong tool for a citation: a model asked
whether a verse is real will usually say yes, because it recognises the verse —
from its training data, not from the sources this lesson was allowed to use.

Three checks, all deterministic:

  1. HEBREW  — every substantial Hebrew run in the lesson must appear either in
     the stored primary corpus, in a retrieved reference, or in the lesson's
     own source material. Compared on the consonantal text, because pointing
     legitimately differs between editions.
  2. PSALMS  — every Tehillim reference must name a real chapter, and must be
     one that was actually put in front of the writer.
  3. NAMES   — a commentator may only be named if the sources name them.

A finding here is not proof of fabrication; it is proof the claim cannot be
traced to anything we supplied, which is the question that actually matters.
"""

from __future__ import annotations

import re

from app.db import supabase
from app.logging import get_logger
from app.services.ingestion.reference_parsers import strip_marks

log = get_logger("services.grounding")

HEBREW_RUN = re.compile(r"[֐-׿‏‎\"'׳״\s\-–—.,:;!?()]{6,}")
HEBREW_LETTER = re.compile(r"[א-ת]")

# A Hebrew run shorter than this is a word or two — a term the teacher uses in
# her own prose ("hakarat hatov", "the word chesed"), not a quotation. Checking
# them would flag her own vocabulary as invented.
MIN_QUOTE_WORDS = 4

PSALM_CITATION = re.compile(
    r"\b(?:tehilli?m|tehilim|psalms?|ps\.)\s*(\d{1,3})(?:\s*[:.]\s*(\d{1,3}))?",
    re.IGNORECASE,
)

# Named authorities the generator might reach for. Detected by pattern where
# there is one ("Rabbi X"), and by name where the name IS the pattern.
TITLED_NAME = re.compile(
    r"\b(?:Rabbi|Rabbeinu|Rav|Reb|Rebbe|Rabbanit|Rebbetzin)\s+"
    r"([A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){0,3})"
)
KNOWN_COMMENTATORS = (
    "Rashi", "Ramban", "Rambam", "Radak", "Ralbag", "Ibn Ezra", "Sforno",
    "Malbim", "Meiri", "Alshich", "Chida", "Ben Ish Chai", "AriZaL", "Ari z\"l",
    "Maharal", "Abarbanel", "Metzudat David", "Metzudas Dovid", "Vilna Gaon",
    "Gra", "Shelah", "Kli Yakar", "Ohr HaChaim", "Or HaChaim", "Netziv",
    "Chafetz Chaim", "Chofetz Chaim", "Tosafot", "Tosafos", "Sfas Emes",
    "Sefat Emet", "Rav Hirsch", "Samson Raphael Hirsch",
)


async def check(
    *,
    sections: list[dict],
    reference_texts: list[str],
    source_text: str | None,
    allowed_psalms: set[int],
) -> list[dict]:
    """
    Return quality issues, in the same shape the rest of the pipeline uses.

    `reference_texts` is everything the writer was shown; `allowed_psalms` is
    which chapters were actually retrieved.
    """
    lesson_text = "\n\n".join((s.get("body") or "") for s in sections)
    if not lesson_text.strip():
        return []

    haystack = _normalise_haystack([*reference_texts, source_text or ""])

    issues: list[dict] = []
    issues.extend(await _check_hebrew(lesson_text, haystack))
    issues.extend(_check_psalms(lesson_text, allowed_psalms))
    issues.extend(_check_attributions(lesson_text, [*reference_texts, source_text or ""]))
    return issues


# ------------------------------------------------------------------ Hebrew


async def _check_hebrew(lesson_text: str, haystack: str) -> list[dict]:
    quotes = _hebrew_quotes(lesson_text)
    if not quotes:
        return []

    db = supabase.service()
    issues: list[dict] = []
    verified = 0

    for quote in quotes[:12]:
        plain = strip_marks(quote)
        if plain and plain in haystack:
            verified += 1
            continue

        try:
            rows = await db.rpc(
                "verify_hebrew_quote",
                {"p_quote": quote, "p_kinds": ["nishmat_text", "scripture"]},
            )
        except supabase.SupabaseError as exc:
            # A grounding check that cannot run must not silently pass. Say so
            # once and stop, rather than reporting every quote as unverified.
            log.warning("quote_verification_failed", error=str(exc))
            return [
                {
                    "severity": "low",
                    "section": None,
                    "message": "The Hebrew in this lesson could not be checked "
                               "against the stored text.",
                    "suggestion": "Check the Hebrew against the siddur by hand.",
                }
            ]

        if rows:
            verified += 1
            continue

        issues.append(
            {
                "severity": "high",
                "section": None,
                "message": (
                    f'The Hebrew "{_shorten(quote)}" is not in the Nishmat text, '
                    f"the Psalms, or any source supplied for this lesson."
                ),
                "suggestion": (
                    "Replace it with the phrase exactly as it appears in the "
                    "supplied text, or remove it."
                ),
            }
        )

    log.info("hebrew_grounding", checked=len(quotes[:12]), verified=verified,
             unverified=len(issues))
    return issues


def _hebrew_quotes(text: str) -> list[str]:
    """
    Substantial runs of Hebrew script, one line at a time, deduplicated.

    Line by line rather than across the whole lesson, because that is how both
    corpora are stored: Nishmat one clause per line, Tehillim one verse per
    line with its English underneath. A quote spanning two lines of the lesson
    would have to match across the English rendering sitting between the two
    verses in the stored text, and would be reported as unverified when it is
    perfectly correct.
    """
    quotes: list[str] = []
    seen: set[str] = set()

    for line in text.splitlines():
        for match in HEBREW_RUN.finditer(line):
            run = match.group(0).strip(" \t\"'.,:;-–—()")
            if len(HEBREW_LETTER.findall(run)) < 8:
                continue
            if len(run.split()) < MIN_QUOTE_WORDS:
                continue

            key = strip_marks(run)
            if key and key not in seen:
                seen.add(key)
                quotes.append(run)

    return quotes


def _normalise_haystack(texts: list[str]) -> str:
    return " ".join(strip_marks(text) for text in texts if text)


# ------------------------------------------------------------------ Psalms


def _check_psalms(lesson_text: str, allowed: set[int]) -> list[dict]:
    issues: list[dict] = []
    seen: set[int] = set()

    for match in PSALM_CITATION.finditer(lesson_text):
        chapter = int(match.group(1))
        if chapter in seen:
            continue
        seen.add(chapter)

        if not 1 <= chapter <= 150:
            issues.append(
                {
                    "severity": "high",
                    "section": None,
                    "message": f"The lesson cites Tehillim {chapter}, which does not exist.",
                    "suggestion": "Remove it or correct the chapter number.",
                }
            )
            continue

        if allowed and chapter not in allowed:
            issues.append(
                {
                    "severity": "medium",
                    "section": None,
                    "message": (
                        f"The lesson cites Tehillim {chapter}, which was not among "
                        f"the sources retrieved for it — so the quotation is being "
                        f"recalled rather than read."
                    ),
                    "suggestion": (
                        f"Check the verse against a Tehillim, or regenerate with "
                        f"Psalm {chapter} named in the brief so the real text is used."
                    ),
                }
            )

    return issues


# ------------------------------------------------------------ attributions


def _check_attributions(lesson_text: str, sources: list[str]) -> list[dict]:
    """
    A named authority must be named in the sources too.

    This is the failure the client cares about most: an interpretation is
    invented and then hung on a real rabbi's name, which makes it sound
    authoritative and is close to impossible to spot while reading.
    """
    supplied = " ".join(sources).lower()
    issues: list[dict] = []
    flagged: set[str] = set()

    for name in KNOWN_COMMENTATORS:
        if name.lower() in lesson_text.lower() and name.lower() not in supplied:
            flagged.add(name)

    for match in TITLED_NAME.finditer(lesson_text):
        name = match.group(1).strip()
        # A single common word after "Rabbi" is usually the start of a sentence
        # rather than a name ("Rabbi Akiva" yes, "Rabbi And" no).
        if len(name) < 4:
            continue
        if name.lower() not in supplied:
            flagged.add(f"{match.group(0)}")

    for name in sorted(flagged)[:6]:
        issues.append(
            {
                "severity": "medium",
                "section": None,
                "message": (
                    f'The lesson attributes something to "{name}", who is not '
                    f"mentioned in any source supplied for it."
                ),
                "suggestion": (
                    "Remove the attribution, or upload the page where they say "
                    "it and regenerate."
                ),
            }
        )

    return issues


def _shorten(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit]}…"
