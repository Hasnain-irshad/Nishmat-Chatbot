"""
Job handler: turn an uploaded file into text.

Runs in the worker, not the request, because transcription can take minutes
and a browser should never be holding a connection open for that.

The handler's contract: leave `source_files.processing_status` in a terminal
state whatever happens. A row stuck on 'processing' is a spinner that never
resolves, which is worse for the admin than an honest failure.
"""

from __future__ import annotations

from app.db import supabase
from app.jobs import queue
from app.logging import get_logger
from app.services import storage
from app.services.ingestion import registry
from app.services.ingestion.base import ExtractionError

log = get_logger("jobs.extract_file")

STAGE_LABELS = {
    "pdf": "Reading the document",
    "docx": "Reading the document",
    "text": "Reading the file",
    "image": "Reading the image",
    "audio": "Transcribing the recording",
}


async def run(job: queue.Job) -> dict:
    file_id = job.payload.get("source_file_id")
    if not file_id:
        raise ValueError("extract_file job has no source_file_id")

    db = supabase.service()

    row = await db.select(
        "source_files",
        columns=(
            "id, lesson_id, original_filename, kind, storage_path, mime_type, "
            "role, reference_book, reference_page, uploaded_by"
        ),
        filters={"id": f"eq.{file_id}"},
        single=True,
    )
    if not row:
        raise ValueError(f"source file {file_id} no longer exists")

    kind = row["kind"]
    filename = row["original_filename"]

    await db.update(
        "source_files",
        {"id": f"eq.{file_id}"},
        {"processing_status": "processing", "error_message": None},
        returning=False,
    )

    try:
        await queue.progress(job.id, "Fetching the file", 10)
        content = await storage.download(row["storage_path"])

        await queue.progress(job.id, STAGE_LABELS.get(kind, "Processing"), 35)
        result = await registry.extract(
            kind, content, filename, purpose=row.get("role") or "lesson_source"
        )

        await queue.progress(job.id, "Saving", 90)
        await db.update(
            "source_files",
            {"id": f"eq.{file_id}"},
            {
                "extracted_text": result.text,
                "extraction_metadata": {
                    **result.metadata,
                    "warnings": result.warnings,
                    "extracted_word_count": result.word_count,
                    "has_hebrew": result.has_hebrew,
                },
                "processing_status": "completed",
                "error_message": None,
            },
            returning=False,
        )

        indexed = 0
        if row.get("role") == "reference" and row.get("lesson_id"):
            await queue.progress(job.id, "Filing the reference", 95)
            indexed = await _index_reference(row, result.text)

        log.info(
            "extraction_complete",
            source_file_id=file_id,
            kind=kind,
            role=row.get("role"),
            words=result.word_count,
            reference_chunks=indexed,
            warnings=len(result.warnings),
        )

        return {
            "source_file_id": file_id,
            "word_count": result.word_count,
            "has_hebrew": result.has_hebrew,
            "warnings": result.warnings,
            "role": row.get("role") or "lesson_source",
            "reference_chunks": indexed,
        }

    except ExtractionError as exc:
        # A known, explainable failure — the message is already written for a
        # person, so show it and do not retry: a corrupt PDF stays corrupt.
        await _mark_failed(db, file_id, str(exc))
        raise _Terminal(str(exc)) from exc

    except storage.StorageError as exc:
        await _mark_failed(db, file_id, "We couldn't retrieve that file from storage.")
        raise  # transient — let the queue retry

    except Exception as exc:
        log.exception("extraction_failed", source_file_id=file_id, kind=kind)
        await _mark_failed(
            db, file_id, "Something went wrong while reading that file."
        )
        raise


async def _index_reference(row: dict, text: str) -> int:
    """
    File an uploaded reference page into the corpus, scoped to its lesson.

    Failure here is logged, not raised. The page is extracted and saved either
    way; what is lost is retrieval, and losing retrieval is much better than
    marking a perfectly good upload as failed and making the admin do it again.
    """
    from app.services import reference_indexing

    try:
        result = await reference_indexing.index_uploaded_page(
            lesson_id=row["lesson_id"],
            source_file_id=row["id"],
            text=text,
            book=row.get("reference_book"),
            page=row.get("reference_page"),
            filename=row["original_filename"],
            created_by=row.get("uploaded_by"),
        )
        return int(result.get("chunks") or 0)
    except Exception:
        log.exception("reference_indexing_failed", source_file_id=row["id"])
        return 0


async def _mark_failed(db, file_id: str, message: str) -> None:
    try:
        await db.update(
            "source_files",
            {"id": f"eq.{file_id}"},
            {"processing_status": "failed", "error_message": message[:500]},
            returning=False,
        )
    except Exception:
        log.exception("could not mark source file failed", source_file_id=file_id)


class _Terminal(Exception):
    """
    A failure that retrying cannot fix.

    The worker recognises this and stops immediately instead of burning the
    remaining attempts on something deterministic.
    """


Terminal = _Terminal
