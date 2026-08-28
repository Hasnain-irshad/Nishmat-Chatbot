"""
Writing a published lesson into the chatbot's index.

The rule this file exists to enforce: **only a published version is ever
indexed.** Learner visibility and chatbot visibility are the same switch, so a
draft cannot be quoted back to a learner and a withdrawn lesson stops being
retrievable the moment it is withdrawn.

Reindexing replaces a lesson's chunks wholesale rather than diffing them. At
three to six chunks per lesson the saving from a diff is nil, and a delete-then-
insert has no state to get wrong.
"""

from __future__ import annotations

from app.db import supabase
from app.llm.provider import get_provider
from app.llm.types import BudgetExceeded, LLMError
from app.logging import get_logger
from app.services import chunking_service

log = get_logger("services.indexing")

# Embedding requests are cheap but not free of latency; batching keeps a
# full-corpus reindex to a sensible number of round trips.
EMBED_BATCH = 64


class IndexingError(Exception):
    """Indexing failed. Safe to show an admin."""


async def index_lesson(lesson_id: str, *, version_id: str | None = None) -> dict:
    """
    (Re)build the chunks for one lesson.

    Refuses to index anything that is not currently published — belt and braces
    behind the callers, which already only invoke this on publish.
    """
    db = supabase.service()

    lesson = await db.select(
        "lessons",
        columns=(
            "id, title, lesson_number, status, published_version_id, "
            "hebrew_phrase, transliteration, deleted_at, series_id"
        ),
        filters={"id": f"eq.{lesson_id}"},
        single=True,
    )
    if not lesson or lesson.get("deleted_at"):
        raise IndexingError("That lesson no longer exists.")

    published_version = lesson.get("published_version_id")

    if lesson.get("status") != "published" or not published_version:
        # Not an error: unpublishing races with a queued index job, and the
        # correct outcome is an empty index, not a failure.
        await db.delete("lesson_chunks", {"lesson_id": f"eq.{lesson_id}"})
        log.info("index_skipped_unpublished", lesson_id=lesson_id)
        return {"lesson_id": lesson_id, "chunks": 0, "skipped": "not published"}

    if version_id and version_id != published_version:
        log.info(
            "index_version_superseded",
            lesson_id=lesson_id,
            requested=version_id,
            published=published_version,
        )
    version_id = published_version

    version = await db.select(
        "lesson_versions",
        columns="id, content",
        filters={"id": f"eq.{version_id}"},
        single=True,
    )
    if not version:
        raise IndexingError("The published version of that lesson is missing.")

    sections = (version.get("content") or {}).get("sections") or []
    if not sections:
        await db.delete("lesson_chunks", {"lesson_id": f"eq.{lesson_id}"})
        return {"lesson_id": lesson_id, "chunks": 0, "skipped": "no content"}

    series_title = await _series_title(db, lesson.get("series_id"))

    chunks = chunking_service.chunk_lesson(
        sections=sections,
        lesson_number=lesson.get("lesson_number"),
        title=lesson.get("title") or "Untitled lesson",
        hebrew_phrase=lesson.get("hebrew_phrase"),
        transliteration=lesson.get("transliteration"),
        series_title=series_title,
    )
    if not chunks:
        await db.delete("lesson_chunks", {"lesson_id": f"eq.{lesson_id}"})
        return {"lesson_id": lesson_id, "chunks": 0, "skipped": "nothing to index"}

    provider = get_provider()
    try:
        embeddings = await _embed_all(provider, [c.embed_text for c in chunks])
    except BudgetExceeded:
        raise
    except LLMError as exc:
        raise IndexingError(f"We couldn't build the search index: {exc}") from exc

    rows = [
        {
            "lesson_id": lesson_id,
            "version_id": version_id,
            "chunk_index": chunk.index,
            "section_key": chunk.section_key,
            "chunk_text": chunk.text,
            # pgvector's text input form. PostgREST passes it through as-is.
            "embedding": "[" + ",".join(f"{value:.6f}" for value in vector) + "]",
            "metadata": chunk.metadata,
        }
        for chunk, vector in zip(chunks, embeddings)
    ]

    # Replace wholesale. The unique key is (version_id, chunk_index), so leaving
    # stale rows from a previous version behind would silently double the index.
    await db.delete("lesson_chunks", {"lesson_id": f"eq.{lesson_id}"})
    await db.insert("lesson_chunks", rows, returning=False)

    log.info(
        "lesson_indexed",
        lesson_id=lesson_id,
        version_id=version_id,
        chunks=len(rows),
        words=sum(c.word_count for c in chunks),
    )
    return {"lesson_id": lesson_id, "chunks": len(rows), "version_id": version_id}


async def unindex_lesson(lesson_id: str) -> dict:
    await supabase.service().delete("lesson_chunks", {"lesson_id": f"eq.{lesson_id}"})
    log.info("lesson_unindexed", lesson_id=lesson_id)
    return {"lesson_id": lesson_id, "chunks": 0}


async def _embed_all(provider, texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start : start + EMBED_BATCH]
        result = await provider.embed(batch, operation="embedding")
        vectors.extend(result.vectors)

    if len(vectors) != len(texts):
        raise IndexingError(
            f"Expected {len(texts)} embeddings but received {len(vectors)}."
        )
    return vectors


async def _series_title(db, series_id: str | None) -> str | None:
    if not series_id:
        return None
    row = await db.select(
        "series", columns="title", filters={"id": f"eq.{series_id}"}, single=True
    )
    return row.get("title") if row else None
