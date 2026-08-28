"""
Splitting a lesson into retrievable pieces.

Chunking is where most RAG systems quietly fail. Fixed-size windows cut a
sentence in half, strip the surrounding context, and hand the model fragments
that no longer say what the lesson said.

These lessons are short — a median of 624 words — and already arrive in
labelled sections. So the section IS the chunk. Only a long section gets split,
and then on sentence boundaries with overlap.

Every chunk is prefixed with a context line naming its lesson and section
before it is embedded. On a 200-word passage that prefix meaningfully changes
what the vector means: "the tantrum image" retrieves far better when the chunk
knows it belongs to Lesson #17 on compassion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A section longer than this is split. Chosen so a typical lesson yields three
# to six chunks — few enough that each keeps its context, many enough that a
# question about one idea does not drag in the whole lesson.
MAX_CHUNK_WORDS = 320
MIN_CHUNK_WORDS = 25
OVERLAP_SENTENCES = 2

# Sections that carry no retrievable meaning on their own.
SKIP_KEYS = {"series_title", "lesson_number", "signoff"}

SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n{2,}")


@dataclass
class Chunk:
    index: int
    text: str
    section_key: str | None
    embed_text: str
    """What actually gets embedded — the text with its context header."""
    metadata: dict = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def chunk_lesson(
    *,
    sections: list[dict],
    lesson_number: int | None,
    title: str,
    hebrew_phrase: str | None = None,
    transliteration: str | None = None,
    series_title: str | None = None,
) -> list[Chunk]:
    """Turn a published lesson's sections into chunks ready to embed."""
    label = _lesson_label(lesson_number, title, transliteration)

    chunks: list[Chunk] = []
    carried: list[str] = []
    carried_keys: list[str] = []

    ordered = sorted(sections, key=lambda s: s.get("order", 0))

    for section in ordered:
        key = section.get("key") or "body"
        body = (section.get("body") or "").strip()

        if not body or key in SKIP_KEYS:
            continue

        # Short sections — a transliteration, a two-line translation — are not
        # worth a chunk of their own, so they ride along with the next one.
        if len(body.split()) < MIN_CHUNK_WORDS:
            carried.append(body)
            carried_keys.append(key)
            continue

        if carried:
            body = "\n\n".join(carried + [body])
            key = carried_keys[0] if carried_keys else key
            carried, carried_keys = [], []

        for piece in _split_section(body):
            chunks.append(
                _build(
                    index=len(chunks),
                    text=piece,
                    section_key=key,
                    label=label,
                    section_label=_section_label(section, key),
                    lesson_number=lesson_number,
                    title=title,
                    hebrew_phrase=hebrew_phrase,
                    transliteration=transliteration,
                    series_title=series_title,
                )
            )

    # Anything still carried (a lesson of only short sections) becomes one chunk.
    if carried:
        text = "\n\n".join(carried)
        if len(text.split()) >= 8:
            chunks.append(
                _build(
                    index=len(chunks),
                    text=text,
                    section_key=carried_keys[0] if carried_keys else None,
                    label=label,
                    section_label=None,
                    lesson_number=lesson_number,
                    title=title,
                    hebrew_phrase=hebrew_phrase,
                    transliteration=transliteration,
                    series_title=series_title,
                )
            )

    return chunks


def _build(
    *,
    index: int,
    text: str,
    section_key: str | None,
    label: str,
    section_label: str | None,
    lesson_number: int | None,
    title: str,
    hebrew_phrase: str | None,
    transliteration: str | None,
    series_title: str | None,
) -> Chunk:
    header = label if not section_label else f"{label} — {section_label}"

    return Chunk(
        index=index,
        text=text,
        section_key=section_key,
        # The header travels into the embedding but is NOT what gets shown back
        # to a reader — `text` is. Retrieval quality and answer quality want
        # different things here.
        embed_text=f"{header}\n\n{text}",
        metadata={
            "lesson_number": lesson_number,
            "title": title,
            "section": section_label,
            "hebrew_phrase": hebrew_phrase,
            "transliteration": transliteration,
            "series_title": series_title,
            "word_count": len(text.split()),
        },
    )


def _split_section(body: str) -> list[str]:
    """Split a long section on sentence boundaries, with a little overlap."""
    words = body.split()
    if len(words) <= MAX_CHUNK_WORDS:
        return [body]

    sentences = [s.strip() for s in SENTENCE_END.split(body) if s and s.strip()]
    if len(sentences) <= 1:
        # One enormous sentence, or prose with no punctuation. Fall back to a
        # word window rather than returning something unusable.
        return [
            " ".join(words[i : i + MAX_CHUNK_WORDS])
            for i in range(0, len(words), MAX_CHUNK_WORDS)
        ]

    pieces: list[str] = []
    current: list[str] = []
    count = 0

    for sentence in sentences:
        length = len(sentence.split())

        if count + length > MAX_CHUNK_WORDS and current:
            pieces.append(" ".join(current))
            # Carry the tail forward so an idea spanning the boundary is not
            # severed — the classic cause of an answer that misses the point.
            current = current[-OVERLAP_SENTENCES:]
            count = sum(len(s.split()) for s in current)

        current.append(sentence)
        count += length

    if current:
        tail = " ".join(current)
        # Avoid leaving a scrap: fold a tiny remainder into the previous piece.
        if pieces and len(tail.split()) < MIN_CHUNK_WORDS:
            pieces[-1] = f"{pieces[-1]} {tail}"
        else:
            pieces.append(tail)

    return pieces


def _lesson_label(
    lesson_number: int | None, title: str, transliteration: str | None
) -> str:
    parts = []
    if lesson_number is not None:
        parts.append(f"Lesson #{lesson_number}")
    parts.append(transliteration or title)
    return " — ".join(parts)


def _section_label(section: dict, key: str) -> str | None:
    if section.get("title"):
        return section["title"]
    if key.startswith("body_"):
        return None
    return key.replace("_", " ").capitalize()
