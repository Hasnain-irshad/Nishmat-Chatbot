"""
Exhaustive search across the COMPLETE stored lessons.

This is not RAG, and the difference is the whole point.

`retrieval_service.search` answers "what is relevant to this question" with the
best handful of chunks. That is right for a learner asking about an idea, and
wrong for "which lessons did I write about Rosh Hashana" — a question whose
correct answer is *every* lesson that qualifies, however many that is.

Three ways the chunk index cannot answer it:

  * `rag_top_k` is 6. Six chunks cannot represent fifty lessons, and a
    multi-topic question embeds to a blurred average that matches none of them
    sharply.
  * `chunking_service.SKIP_KEYS` omits some sections from the index entirely,
    so absence from the chunks genuinely does not mean absence from the lesson.
  * ranking by similarity answers "which is closest", never "which all match".

So this module reads `lesson_versions.content_text` — the complete stored
lesson, exactly as published — for every published lesson, and matches against
all of it. The corpus is about half a megabyte; scanning it in process costs
milliseconds and removes an entire class of "the chatbot says it isn't there"
failure.

MATCHING IS NORMALISED, and that is not a nicety. Lesson #9 is titled
"Podeh u'Matzil, Ve'oneh u'Merachem" with a TYPOGRAPHIC apostrophe (U+2019).
A search for "podeh u'matzil" typed with an ASCII apostrophe finds nothing, and
the honest-looking answer "no lesson covers that" is simply false.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field

from app.db import supabase
from app.logging import get_logger

log = get_logger("services.transcript_search")

# The corpus changes only when a lesson is published. Re-reading it on every
# query would be wasteful; holding it forever would serve stale text after a
# publish. A minute is short enough that nobody notices and long enough that a
# burst of searches costs one read.
CACHE_TTL_SECONDS = 60

_cache: dict = {"at": 0.0, "lessons": []}


# ---------------------------------------------------------------- normalising

# Nikud, cantillation, and the Hebrew word separators. Reused rather than
# reinvented: `reference_parsers.strip_marks` already encodes which of these
# delete and which become a space (see CONTEXT.md 9.7 — getting that wrong
# welds words together).
_APOSTROPHES = dict.fromkeys(map(ord, "'‘’ʼʻ`´"), None)

# Hyphens of every kind, plus the Hebrew maqaf, become a SPACE. The corpus
# transliterates some lessons syllable by syllable ("Meh-cheh-rev
# hi-tzahl-tah-nu"), so a hyphen is a word boundary here, not a joiner.
_HYPHENS = re.compile(r"[-‐-―−־]+")

_WHITESPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """
    Fold a string to the form both sides of a comparison are matched in.

    Deliberately aggressive: apostrophes vanish, hyphens become spaces, Hebrew
    points are stripped, case is folded. Two spellings of the same phrase have
    to collide, because the alternative is telling the teacher she never wrote
    a lesson she plainly did.
    """
    from app.services.ingestion.reference_parsers import strip_marks

    text = unicodedata.normalize("NFC", text or "")
    text = strip_marks(text)            # nikud out, maqaf/paseq to space
    text = text.translate(_APOSTROPHES)  # u'Matzil == uMatzil == u’Matzil
    text = _HYPHENS.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip().lower()


def _squeeze(text: str) -> str:
    """Normalised AND space-free, so "u Matzil" also matches "umatzil"."""
    return normalise(text).replace(" ", "")


# ------------------------------------------------------------------- topics

# The vocabulary this teacher actually uses, in the spellings she actually
# uses. Transliteration has no standard, so a term the client types one way
# ("Sukkot") appears in her lessons another ("Sukkos", "Succos").
#
# Not exhaustive and not meant to be — a caller may pass any terms it likes.
# These are the ones worth getting right without being asked.
TOPIC_VARIANTS: dict[str, list[str]] = {
    "rosh hashana": [
        "rosh hashana", "rosh hashanah", "rosh hashonoh", "ראש השנה",
        "yom hadin", "יום הדין", "day of judgment", "day of judgement",
        "yom teruah", "new year",
    ],
    "aseret yemei teshuva": [
        "aseret yemei teshuva", "aseres yemei teshuvah", "עשרת ימי תשובה",
        "ten days of repentance", "ten days of teshuva", "teshuva", "teshuvah",
        "תשובה",
    ],
    "sukkot": [
        "sukkot", "sukkos", "succot", "succos", "סוכות", "sukkah", "succah",
        "סוכה", "ushpizin", "אושפיזין", "lulav", "לולב", "etrog", "אתרוג",
    ],
    "podeh umatzil": [
        "podeh umatzil", "podeh u matzil", "poydeh umatzil", "פודה ומציל",
    ],
    "podeh": ["podeh", "poydeh", "פודה"],
    "consistency": [
        "consistency", "consistent", "consistently", "steadfast",
        "day after day", "every single day", "showing up", "perseverance",
        "persistence", "routine", "regularly",
    ],
    "hope": [
        "hope", "hopeful", "hoping", "hopelessness", "tikvah", "tikva",
        "תקווה", "תקוה", "yearning", "longing", "optimism",
    ],
}


def expand(topic: str) -> list[str]:
    """The search terms for a topic: its known variants, or the topic itself."""
    key = normalise(topic)
    for name, variants in TOPIC_VARIANTS.items():
        if normalise(name) == key:
            return variants
    # An unknown topic is still searchable — just without hand-written synonyms.
    return [topic]


# ------------------------------------------------------------------- results


@dataclass
class TranscriptMatch:
    lesson_id: str
    lesson_number: int | None
    title: str
    word_count: int
    hits: int
    """Total occurrences across every term searched."""
    matched_terms: list[str] = field(default_factory=list)
    evidence: str = ""
    """A short window around the first hit, so a person can judge relevance."""


# ------------------------------------------------------------------ the corpus


async def load_corpus(*, force: bool = False) -> list[dict]:
    """
    Every published lesson with its COMPLETE stored text.

    One query for the whole corpus. At ~0.5 MB that is cheaper than the round
    trips a per-lesson fetch would cost, and it is the only way to answer a
    question whose scope is "all of them".
    """
    now = time.monotonic()
    if not force and _cache["lessons"] and now - _cache["at"] < CACHE_TTL_SECONDS:
        return _cache["lessons"]

    db = supabase.service()
    lessons = await db.select(
        "lessons",
        columns="id, lesson_number, title, published_version_id",
        filters={"status": "eq.published", "deleted_at": "is.null"},
        order="lesson_number.asc",
    )
    versions = await db.select(
        "lesson_versions", columns="id, content_text, word_count"
    )
    by_id = {v["id"]: v for v in versions}

    corpus: list[dict] = []
    for lesson in lessons:
        version = by_id.get(lesson.get("published_version_id"))
        text = (version or {}).get("content_text") or ""
        if not text.strip():
            continue
        corpus.append(
            {
                "id": lesson["id"],
                "lesson_number": lesson.get("lesson_number"),
                "title": lesson.get("title") or "Untitled lesson",
                "word_count": (version or {}).get("word_count") or len(text.split()),
                "text": text,
                # Both folded forms are precomputed once per cache fill rather
                # than per query — the whole corpus is normalised on every
                # search otherwise.
                "flat": normalise(f"{lesson.get('title') or ''} {text}"),
                "squeezed": _squeeze(f"{lesson.get('title') or ''} {text}"),
            }
        )

    _cache["lessons"] = corpus
    _cache["at"] = now
    log.info("transcript_corpus_loaded", lessons=len(corpus),
             chars=sum(len(c["text"]) for c in corpus))
    return corpus


# ------------------------------------------------------------------ searching


async def search(
    terms: list[str], *, limit: int | None = None, min_hits: int = 1
) -> list[TranscriptMatch]:
    """
    Every published lesson whose complete text matches any of `terms`.

    Exhaustive by design: `limit` caps what is RETURNED for display, never what
    is searched, and the count of true matches is reported separately so a
    caller can say "showing 10 of 34" honestly rather than implying there were
    only 10.
    """
    corpus = await load_corpus()
    wanted = [t for t in (terms or []) if t and t.strip()]
    if not wanted:
        return []

    folded = [(t, normalise(t), _squeeze(t)) for t in wanted]
    results: list[TranscriptMatch] = []

    for entry in corpus:
        hits = 0
        matched: list[str] = []
        first_at = -1

        for original, flat, squeezed in folded:
            if not flat:
                continue
            # Counted in the spaced form; falls back to the space-free form so
            # "u'Matzil" and "umatzil" and "u matzil" all find each other.
            count = entry["flat"].count(flat)
            if not count and squeezed:
                count = entry["squeezed"].count(squeezed)
            if count:
                hits += count
                matched.append(original)
                where = entry["flat"].find(flat)
                if where >= 0 and (first_at < 0 or where < first_at):
                    first_at = where

        if hits >= min_hits:
            results.append(
                TranscriptMatch(
                    lesson_id=entry["id"],
                    lesson_number=entry["lesson_number"],
                    title=entry["title"],
                    word_count=entry["word_count"],
                    hits=hits,
                    matched_terms=matched,
                    evidence=_evidence(entry["flat"], first_at),
                )
            )

    # Most mentions first — a lesson that says "Rosh Hashana" ten times is more
    # likely to BE about it than one that mentions it once in passing. Lesson
    # number breaks ties so the order is stable between identical queries.
    results.sort(key=lambda m: (-m.hits, m.lesson_number or 0))
    return results[:limit] if limit else results


def _evidence(flat: str, at: int, width: int = 90) -> str:
    """A short window around the first hit — enough to judge, not to reproduce."""
    if at < 0:
        return ""
    start = max(0, at - width // 3)
    snippet = flat[start : start + width].strip()
    return f"…{snippet}…" if snippet else ""


async def search_topic(topic: str, **kwargs) -> list[TranscriptMatch]:
    """Search a named topic, expanded through its known spelling variants."""
    return await search(expand(topic), **kwargs)


# A request to survey the corpus rather than to answer a question:
# "which lessons did I write about X", "send me the lesson numbers for X",
# "list the lessons on X". The answer is a SET of lessons, not a paragraph.
SURVEY_REQUEST = re.compile(
    r"\b(?:"
    r"which\s+lessons?|what\s+lessons?|lessons?\s+numbers?|list\s+(?:the\s+)?lessons?|"
    r"lessons?\s+(?:that\s+)?(?:i|she|we)\s+(?:prepared|wrote|taught|made|did)|"
    r"(?:all|every)\s+(?:the\s+)?lessons?|find\s+(?:me\s+)?(?:the\s+)?lessons?|"
    r"send\s+me\s+the\s+lessons?"
    r")\b",
    re.IGNORECASE,
)


def survey_request(question: str) -> bool:
    """Is this asking which lessons cover something, rather than asking about it?"""
    return bool(SURVEY_REQUEST.search(question or ""))


def topics_in(question: str) -> list[str]:
    """
    The topics a survey question is asking about.

    Two sources, combined. Any known topic named anywhere in the question is
    picked up; anything listed after a colon is treated as an explicit list,
    because that is how the client actually writes these requests — a colon and
    then one topic per line.
    """
    text = question or ""
    found: list[str] = []

    flat = normalise(text)
    for name, variants in TOPIC_VARIANTS.items():
        if any(normalise(v) in flat for v in variants):
            found.append(name)

    # Whatever follows a colon, split on lines and commas. Keeps topics we have
    # no synonym list for — they are still searchable, just literally.
    if ":" in text:
        listed = text.split(":", 1)[1]
        for piece in re.split(r"[\n,;]+|\band\b", listed):
            piece = re.sub(
                r"^\s*(?:about|on|for|the|concept of|words?|lessons?)\s+", "",
                piece.strip(), flags=re.IGNORECASE,
            ).strip(" .-–—")
            if len(piece) < 3:
                continue
            if not any(normalise(piece) == normalise(f) for f in found):
                # Skip a listed item already covered by a known topic above.
                if not any(normalise(piece) in normalise(f)
                           or normalise(f) in normalise(piece) for f in found):
                    found.append(piece)

    seen: set[str] = set()
    return [t for t in found if not (normalise(t) in seen or seen.add(normalise(t)))]


async def get_transcript(lesson_number: int) -> dict | None:
    """
    One lesson's complete stored text.

    Thin wrapper over the same direct read the chatbot's verbatim path uses, so
    a search result can be turned into the full lesson without going near the
    chunk index.
    """
    from app.services import retrieval_service

    return await retrieval_service.load_full_lesson(lesson_number)
