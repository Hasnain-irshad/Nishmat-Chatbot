"""
Writing reference material into the corpus.

Two callers, one code path:

  * `backend/scripts/index_references.py` loads the permanent corpus — the
    Nishmat text, the Psalms, the client's reference document. Run rarely,
    idempotently, by a person.
  * the extraction worker calls `index_uploaded_page` when an admin attaches a
    photographed book page to a lesson. Run often, automatically, scoped to
    that lesson.

The difference between them is one field: `lesson_id`. A lesson-scoped document
is retrievable only while generating that lesson, and dies with it.
"""

from __future__ import annotations

from app.db import supabase
from app.llm.provider import get_provider
from app.llm.types import BudgetExceeded, LLMError
from app.logging import get_logger
from app.services.ingestion.reference_parsers import ReferenceChunk

log = get_logger("services.reference_indexing")

EMBED_BATCH = 64


class ReferenceIndexError(Exception):
    """Indexing failed. The message is safe to show an admin."""


async def upsert_document(
    *,
    title: str,
    kind: str,
    authority: str,
    chunks: list[ReferenceChunk],
    variant: str | None = None,
    language: str = "he",
    attribution: str | None = None,
    notes: str | None = None,
    lesson_id: str | None = None,
    source_file_id: str | None = None,
    created_by: str | None = None,
) -> dict:
    """
    Replace a reference document and its chunks, wholesale.

    Replace rather than diff: these documents change when someone hands us a
    corrected file, and at a few thousand chunks the saving from a diff is not
    worth the class of bug where a stale chunk survives an edit and keeps being
    retrieved as though it were current.
    """
    if not chunks:
        raise ReferenceIndexError(f"There is nothing to index in \"{title}\".")

    db = supabase.service()

    existing = await _find_document(db, kind=kind, variant=variant, lesson_id=lesson_id,
                                    source_file_id=source_file_id)

    payload = {
        "title": title,
        "kind": kind,
        "authority": authority,
        "variant": variant,
        "language": language,
        "attribution": attribution,
        "notes": notes,
        "lesson_id": lesson_id,
        "source_file_id": source_file_id,
        "is_active": True,
        "metadata": {"chunk_count": len(chunks)},
    }

    if existing:
        document_id = existing["id"]
        await db.update("reference_documents", {"id": f"eq.{document_id}"}, payload,
                        returning=False)
        # Chunks cascade on document delete, but the document is being kept —
        # so clear them explicitly before writing the new set.
        await db.delete("reference_chunks", {"document_id": f"eq.{document_id}"})
    else:
        payload["created_by"] = created_by
        created = await db.insert("reference_documents", payload)
        row = created[0] if isinstance(created, list) else created
        document_id = row["id"]

    vectors = await _embed_all([_embed_text(chunk, title) for chunk in chunks])

    rows = [
        {
            "document_id": document_id,
            "chunk_index": index,
            "ref": chunk.ref,
            "heading": chunk.heading,
            "chunk_text": chunk.text,
            "embedding": "[" + ",".join(f"{value:.6f}" for value in vector) + "]",
            "kind": kind,
            "authority": authority,
            "lesson_id": lesson_id,
            "metadata": chunk.metadata,
        }
        for index, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]

    # PostgREST has a request-size ceiling and these payloads carry a 1536-float
    # vector per row, so a 500-chunk document has to go in batches.
    for start in range(0, len(rows), 100):
        await db.insert("reference_chunks", rows[start : start + 100], returning=False)

    log.info(
        "reference_indexed",
        document_id=document_id,
        title=title,
        kind=kind,
        variant=variant,
        chunks=len(rows),
        lesson_scoped=bool(lesson_id),
    )
    return {"document_id": document_id, "chunks": len(rows), "title": title}


async def index_uploaded_page(
    *,
    lesson_id: str,
    source_file_id: str,
    text: str,
    book: str | None,
    page: str | None,
    filename: str,
    created_by: str | None = None,
) -> dict:
    """Index one photographed book page, scoped to a single lesson."""
    from app.services.ingestion.reference_parsers import parse_uploaded_page

    chunks = parse_uploaded_page(text, book=book, page=page, filename=filename)
    if not chunks:
        raise ReferenceIndexError("There was no readable text on that page.")

    label = book or filename
    return await upsert_document(
        title=f"{label} — p. {page}" if page else label,
        kind="commentary",
        # A photographed page of a published book is a real authority, but it
        # is second-hand here: we have the page the admin chose to send, not
        # the argument around it. Attribute it; never extrapolate from it.
        authority="secondary",
        chunks=chunks,
        variant=None,
        language="en",
        attribution=book,
        notes="Uploaded by an administrator for this lesson.",
        lesson_id=lesson_id,
        source_file_id=source_file_id,
        created_by=created_by,
    )


async def remove_lesson_references(lesson_id: str) -> int:
    """Drop every reference document uploaded for one lesson."""
    db = supabase.service()
    rows = await db.select(
        "reference_documents",
        columns="id",
        filters={"lesson_id": f"eq.{lesson_id}"},
    )
    if rows:
        await db.delete("reference_documents", {"lesson_id": f"eq.{lesson_id}"})
    return len(rows)


# ------------------------------------------------------------------ helpers


async def _find_document(
    db, *, kind: str, variant: str | None, lesson_id: str | None,
    source_file_id: str | None,
) -> dict | None:
    """
    The row this content should replace, if there is one.

    A lesson-scoped document is identified by the file it came from — two
    photographs of different pages are two documents. A global one is
    identified by (kind, variant), which is what the unique index enforces.
    """
    if lesson_id and source_file_id:
        return await db.select(
            "reference_documents",
            columns="id",
            filters={"source_file_id": f"eq.{source_file_id}"},
            single=True,
        )

    filters = {"kind": f"eq.{kind}", "lesson_id": "is.null"}
    filters["variant"] = f"eq.{variant}" if variant else "is.null"
    return await db.select(
        "reference_documents", columns="id", filters=filters, single=True
    )


def _embed_text(chunk: ReferenceChunk, title: str) -> str:
    """
    What actually gets embedded.

    The heading and the address travel into the vector but are not what gets
    shown back. For a Psalm this is the difference between a chunk that can be
    found by "psalm about being rescued from a stronger enemy" and one that can
    only be found by someone who already types vocalised Hebrew.
    """
    parts = [title]
    if chunk.heading:
        parts.append(chunk.heading)
    if chunk.ref and chunk.ref != chunk.heading:
        parts.append(chunk.ref)
    return "\n".join(parts) + "\n\n" + chunk.text


def _fit_to_budget(text: str) -> str:
    """
    Last-resort truncation before embedding.

    The chunkers keep pieces under the limit; this exists because the embedding
    API rejects the whole BATCH when a single item is too long, so one bad chunk
    does not degrade a document — it loses every chunk in the batch with it.
    Truncating one chunk's vector is a far better outcome than a page that
    uploaded cleanly, reported success, and silently indexed nothing.

    Only ever affects what is EMBEDDED. The stored text is untouched, so the
    admin still reads the whole page and the model is still shown all of it.
    """
    from app.services.ingestion.reference_parsers import (
        MAX_EMBED_TOKENS,
        estimate_tokens,
    )

    tokens = estimate_tokens(text)
    if tokens <= MAX_EMBED_TOKENS:
        return text

    # 0.95, not 1.0: the estimate is per-character and rounds up, so cutting to
    # exactly the budget lands a token or two over it.
    keep = max(1, int(len(text) * MAX_EMBED_TOKENS * 0.95 / tokens))
    log.warning(
        "embed_text_truncated",
        estimated_tokens=tokens,
        chars_before=len(text),
        chars_after=keep,
    )
    return text[:keep]


async def _embed_all(texts: list[str]) -> list[list[float]]:
    provider = get_provider()
    vectors: list[list[float]] = []
    texts = [_fit_to_budget(text) for text in texts]

    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start : start + EMBED_BATCH]
        try:
            result = await provider.embed(batch, operation="embedding")
        except BudgetExceeded:
            raise
        except LLMError as exc:
            raise ReferenceIndexError(f"We couldn't build the index: {exc}") from exc
        vectors.extend(result.vectors)

    if len(vectors) != len(texts):
        raise ReferenceIndexError(
            f"Expected {len(texts)} embeddings but received {len(vectors)}."
        )
    return vectors
