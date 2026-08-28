"""
Source file upload and review.

Admin-only — mounted under the admin router, which carries `require_admin`.
Learners have no access to source material at any level: not through the API,
not through RLS, and not through storage.

Upload returns immediately with a job id. Extraction runs in the worker,
because transcribing a six-minute recording is not something to do inside an
HTTP request.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import AdminDep
from app.db import supabase
from app.jobs import queue
from app.logging import get_logger
from app.services import file_validation, storage
from app.services.ingestion import registry

log = get_logger("api.files")

router = APIRouter(prefix="/files", tags=["admin:files"])

# Read the upload in bounded chunks so a huge body cannot exhaust memory
# before the size check gets a chance to run.
CHUNK = 1024 * 1024
HARD_CAP = 120 * 1024 * 1024


class UploadResponse(BaseModel):
    source_file_id: str
    job_id: str | None
    kind: str
    filename: str
    size_bytes: int
    duplicate_of: str | None = None
    message: str
    role: str = "lesson_source"


# What an upload IS, not what format it happens to be in.
#
#   lesson_source — the recording or document this lesson is made from.
#   reference     — a page of a book to consult while writing it. Kept apart
#                   all the way through: it is attributed, it is scoped to one
#                   lesson, and it never reaches a learner.
UPLOAD_ROLES = {"lesson_source", "reference"}

# A reference upload is a page someone photographed. Anything else is either a
# mistake or an attempt to bulk-load a book, and neither should go through here.
REFERENCE_KINDS = {"image", "pdf"}


class SourceFileResponse(BaseModel):
    id: str
    lesson_id: str | None
    original_filename: str
    kind: str
    mime_type: str
    size_bytes: int
    processing_status: str
    error_message: str | None
    extracted_text: str | None
    extraction_metadata: dict
    created_at: str
    role: str = "lesson_source"
    reference_book: str | None = None
    reference_page: str | None = None


class TextUpdate(BaseModel):
    extracted_text: str = Field(min_length=1, max_length=500_000)


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_source_file(
    user: AdminDep,
    file: UploadFile = File(...),
    lesson_id: str | None = Form(default=None),
    role: str = Form(default="lesson_source"),
    reference_book: str | None = Form(default=None),
    reference_page: str | None = Form(default=None),
) -> UploadResponse:
    content = await _read_capped(file)

    if role not in UPLOAD_ROLES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown upload type '{role}'.",
        )

    try:
        validated = file_validation.validate(file.filename or "upload", content)
    except file_validation.ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    if role == "reference":
        if not lesson_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "A reference page has to belong to a lesson. Create the lesson "
                "first, then attach the page to it.",
            )
        if validated.kind not in REFERENCE_KINDS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Reference pages should be photographs or scans — an image or a "
                f"PDF. That file is a {validated.kind} file.",
            )

    db = supabase.service()

    # Identical bytes already uploaded? Reuse the extraction rather than
    # paying to transcribe the same recording twice.
    #
    # Scoped to the same role: the same photograph attached once as a lesson's
    # own material and once as a reference for a different lesson has to be two
    # rows, because the two are treated differently downstream.
    existing = await db.select(
        "source_files",
        columns="id, processing_status, original_filename",
        filters={
            "checksum_sha256": f"eq.{validated.checksum_sha256}",
            "processing_status": "eq.completed",
            "role": f"eq.{role}",
            "lesson_id": f"eq.{lesson_id}" if lesson_id else "is.null",
        },
        single=True,
    )
    if existing:
        log.info("upload_deduplicated", checksum=validated.checksum_sha256[:12])
        return UploadResponse(
            source_file_id=existing["id"],
            job_id=None,
            kind=validated.kind,
            filename=validated.filename,
            size_bytes=validated.size_bytes,
            duplicate_of=existing["id"],
            role=role,
            message=(
                f"This file was already uploaded as "
                f"\"{existing['original_filename']}\" and has been processed."
            ),
        )

    key = storage.build_key(validated.kind, validated.filename)
    try:
        await storage.upload(key, content, validated.mime_type)
    except storage.StorageError as exc:
        log.error("upload_storage_failed", error=str(exc))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "We couldn't save that file. Please try again.",
        ) from None

    row = await db.insert(
        "source_files",
        {
            "lesson_id": lesson_id,
            "original_filename": validated.filename,
            "mime_type": validated.mime_type,
            "size_bytes": validated.size_bytes,
            "checksum_sha256": validated.checksum_sha256,
            "kind": validated.kind,
            "storage_path": key,
            "processing_status": "pending",
            "uploaded_by": user.id,
            "role": role,
            "reference_book": (reference_book or "").strip()[:200] or None,
            "reference_page": (reference_page or "").strip()[:60] or None,
        },
    )
    source_file_id = row[0]["id"] if isinstance(row, list) else row["id"]

    # Formats needing a model are queued anyway, so the failure is recorded on
    # the file where the admin will see it — but say so up front.
    message = "Uploaded. Processing has started."
    from app.config import get_settings

    settings = get_settings()
    if registry.requires_llm(validated.kind) and not settings.openai_api_key:
        if settings.llm_mode == "live":
            message = (
                f"Uploaded, but {validated.kind} files need the OpenAI key, "
                f"which is not configured yet."
            )
        else:
            message = (
                f"Uploaded. Running in mock mode, so this {validated.kind} file "
                f"will produce placeholder text."
            )

    job_id = await queue.enqueue(
        queue.JobType.EXTRACT_FILE,
        {"source_file_id": source_file_id},
        lesson_id=lesson_id,
        created_by=user.id,
    )

    return UploadResponse(
        source_file_id=source_file_id,
        job_id=job_id,
        kind=validated.kind,
        filename=validated.filename,
        size_bytes=validated.size_bytes,
        role=role,
        message=message,
    )


@router.get("/{file_id}", response_model=SourceFileResponse)
async def get_source_file(file_id: str, user: AdminDep) -> SourceFileResponse:
    row = await supabase.service().select(
        "source_files",
        columns=(
            "id, lesson_id, original_filename, kind, mime_type, size_bytes, "
            "processing_status, error_message, extracted_text, "
            "extraction_metadata, created_at, role, reference_book, reference_page"
        ),
        filters={"id": f"eq.{file_id}"},
        single=True,
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That file was not found.")
    return SourceFileResponse(**row)


@router.get("/{file_id}/download-url")
async def get_download_url(file_id: str, user: AdminDep) -> dict:
    """A short-lived signed URL. The bucket itself stays private."""
    row = await supabase.service().select(
        "source_files",
        columns="id, storage_path, original_filename",
        filters={"id": f"eq.{file_id}"},
        single=True,
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That file was not found.")

    try:
        url = await storage.signed_url(row["storage_path"], expires_in=900)
    except storage.StorageError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "We couldn't produce a download link right now.",
        ) from None

    return {"url": url, "expires_in": 900, "filename": row["original_filename"]}


@router.patch("/{file_id}/text", response_model=SourceFileResponse)
async def correct_extracted_text(
    file_id: str, payload: TextUpdate, user: AdminDep
) -> SourceFileResponse:
    """
    Let the admin fix the extracted text before it feeds the generator.

    This matters most for audio: a transcript that mangles a Hebrew term will
    carry that error into the lesson, and catching it here is far cheaper than
    correcting the finished draft.
    """
    db = supabase.service()

    existing = await db.select(
        "source_files",
        columns="id, extraction_metadata",
        filters={"id": f"eq.{file_id}"},
        single=True,
    )
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That file was not found.")

    metadata = existing.get("extraction_metadata") or {}
    metadata["manually_corrected"] = True

    updated = await db.update(
        "source_files",
        {"id": f"eq.{file_id}"},
        {
            "extracted_text": payload.extracted_text,
            "extraction_metadata": metadata,
            "processing_status": "completed",
            "error_message": None,
        },
    )
    row = updated[0] if isinstance(updated, list) else updated
    log.info("extracted_text_corrected", source_file_id=file_id, by=user.id)

    return await get_source_file(file_id, user)


async def _read_capped(file: UploadFile) -> bytes:
    """Read the body, refusing anything absurd before it fills memory."""
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > HARD_CAP:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"That file is larger than {HARD_CAP // 1_048_576} MB.",
            )
        chunks.append(chunk)

    return b"".join(chunks)
