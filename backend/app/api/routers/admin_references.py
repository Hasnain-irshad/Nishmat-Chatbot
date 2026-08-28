"""
Reference material.

Two quite different things live behind this one prefix, and the difference is
the whole point:

  * the CORPUS — the Nishmat text, the Psalms, the teacher's own reference
    document. Permanent, shared by every lesson, loaded by a person running the
    indexer. Read-only here; the admin needs to see what the system actually
    has, because "no English translation is loaded" explains a lesson with no
    English quotations far better than the lesson does.

  * lesson PAGES — photographs of books the client owns physically, attached to
    one lesson while it is being written. Created through the normal upload
    endpoint with `role=reference`, listed and removed here.

Mounted under the admin router, so every route inherits `require_admin`. None
of this is ever reachable by a learner: not through the API, not through RLS,
and not through the chatbot, which searches a different table.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from app.api.deps import AdminDep
from app.db import supabase
from app.logging import get_logger
from app.services import reference_service

log = get_logger("api.admin_references")

router = APIRouter(prefix="/references", tags=["admin:references"])


class CorpusDocument(BaseModel):
    id: str
    title: str
    kind: str
    authority: str
    variant: str | None
    language: str | None
    attribution: str | None
    chunks: int | None
    is_active: bool
    updated_at: str | None


class CorpusStatus(BaseModel):
    documents: list[CorpusDocument]
    missing: list[str]
    """References the system is designed to use but does not yet hold."""


class ReferencePage(BaseModel):
    source_file_id: str
    filename: str
    kind: str
    book: str | None
    page: str | None
    processing_status: str
    error_message: str | None
    word_count: int | None
    indexed_chunks: int
    created_at: str


# What the pipeline is built to use. Listed explicitly so an absence is
# reported as an absence, rather than being invisible until a lesson comes out
# thin and nobody can say why.
EXPECTED_CORPUS = [
    ("nishmat_text", "Nishmat Kol Chai — Hebrew, Edot HaMizrach"),
    ("scripture", "Tehillim — complete Hebrew, chapters 1–150"),
    ("commentary", "Reference material supplied by the teacher"),
    ("translation", "An authoritative English translation of Nishmat"),
    ("transcript", "Teaching transcripts (NJOP)"),
]


@router.get("/corpus", response_model=CorpusStatus)
async def get_corpus(user: AdminDep) -> CorpusStatus:
    documents = await reference_service.corpus_status()
    present = {doc["kind"] for doc in documents}

    return CorpusStatus(
        documents=[CorpusDocument(**doc) for doc in documents],
        missing=[label for kind, label in EXPECTED_CORPUS if kind not in present],
    )


@router.get("/lessons/{lesson_id}/pages", response_model=list[ReferencePage])
async def list_lesson_pages(lesson_id: str, user: AdminDep) -> list[ReferencePage]:
    """Every reference page attached to one lesson, with its indexing state."""
    db = supabase.service()

    files = await db.select(
        "source_files",
        columns=(
            "id, original_filename, kind, reference_book, reference_page, "
            "processing_status, error_message, extraction_metadata, created_at"
        ),
        filters={"lesson_id": f"eq.{lesson_id}", "role": "eq.reference"},
        order="created_at.asc",
    )
    if not files:
        return []

    # How many chunks each page produced. A page that extracted but indexed
    # nothing is the failure mode worth surfacing: the admin sees "uploaded",
    # the generator sees nothing, and nobody finds out until the draft is wrong.
    documents = await db.select(
        "reference_documents",
        columns="source_file_id, metadata",
        filters={"lesson_id": f"eq.{lesson_id}"},
    )
    chunk_counts = {
        row["source_file_id"]: (row.get("metadata") or {}).get("chunk_count") or 0
        for row in documents or []
        if row.get("source_file_id")
    }

    return [
        ReferencePage(
            source_file_id=row["id"],
            filename=row["original_filename"],
            kind=row["kind"],
            book=row.get("reference_book"),
            page=row.get("reference_page"),
            processing_status=row["processing_status"],
            error_message=row.get("error_message"),
            word_count=(row.get("extraction_metadata") or {}).get(
                "extracted_word_count"
            ),
            indexed_chunks=chunk_counts.get(row["id"], 0),
            created_at=row["created_at"],
        )
        for row in files
    ]


@router.delete(
    "/lessons/{lesson_id}/pages/{source_file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # A 204 carries no body. `from __future__ import annotations` turns the
    # `-> None` hint into a string, which FastAPI would otherwise resolve to a
    # response model and then reject for a 204.
    response_model=None,
    response_class=Response,
)
async def remove_lesson_page(
    lesson_id: str, source_file_id: str, user: AdminDep
) -> None:
    """
    Detach a reference page from a lesson.

    Removes the indexed text as well as the file. Leaving the chunks behind
    would mean a page the admin believes they deleted still steering the next
    generation — the kind of ghost that is very hard to diagnose from a draft.
    """
    db = supabase.service()

    row = await db.select(
        "source_files",
        columns="id, storage_path, role",
        filters={
            "id": f"eq.{source_file_id}",
            "lesson_id": f"eq.{lesson_id}",
            "role": "eq.reference",
        },
        single=True,
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That page was not found.")

    await db.delete("reference_documents", {"source_file_id": f"eq.{source_file_id}"})
    await db.delete("source_files", {"id": f"eq.{source_file_id}"})

    # The stored object is best-effort: the row is gone either way, and a file
    # left in a private bucket is a tidiness problem, not a correctness one.
    try:
        from app.services import storage

        await storage.delete(row["storage_path"])
    except Exception:
        log.warning("reference_object_not_removed", path=row.get("storage_path"))

    log.info(
        "reference_page_removed",
        lesson_id=lesson_id,
        source_file_id=source_file_id,
        by=user.id,
    )
