"""
Lesson management.

Mounted under the admin router, so every route here inherits `require_admin`.

Two invariants this file exists to protect:

  * versions are immutable — an edit creates a new one, never rewrites an old;
  * publishing is a separate, explicit action, and is the only thing that makes
    content visible to a learner.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.api.deps import AdminDep
from app.db import supabase
from app.jobs import queue
from app.llm.types import BudgetExceeded
from app.logging import get_logger
from app.services import modification_service, publishing_service

log = get_logger("api.admin_lessons")

router = APIRouter(prefix="/lessons", tags=["admin:lessons"])

LESSON_COLUMNS = (
    "id, series_id, template_id, title, lesson_number, sequence_position, "
    "hebrew_phrase, transliteration, translation, summary, status, "
    "current_version_id, published_version_id, published_at, needs_review, "
    "review_notes, created_at, updated_at, generation_brief"
)


# ------------------------------------------------------------------- schemas


class LessonSummary(BaseModel):
    id: str
    title: str
    lesson_number: int | None
    hebrew_phrase: str | None
    transliteration: str | None
    status: str
    needs_review: bool
    review_notes: str | None
    published_at: str | None
    updated_at: str
    has_unpublished_changes: bool = False


class LessonDetail(LessonSummary):
    series_id: str | None
    template_id: str | None
    translation: str | None
    summary: str | None
    current_version_id: str | None
    published_version_id: str | None
    created_at: str
    current_version: dict | None = None
    generation_brief: dict | None = None


class VersionSummary(BaseModel):
    id: str
    version_number: int
    origin: str
    modification_instruction: str | None
    word_count: int
    created_at: str
    created_by: str | None
    is_published: bool = False
    is_current: bool = False


class LessonUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    lesson_number: int | None = Field(default=None, ge=0, le=9999)
    hebrew_phrase: str | None = None
    transliteration: str | None = None
    translation: str | None = None
    summary: str | None = Field(default=None, max_length=2000)
    template_id: str | None = None
    needs_review: bool | None = None
    review_notes: str | None = None


class VersionCreate(BaseModel):
    """A manual edit. Always produces a new version — never an overwrite."""

    content: dict[str, Any]
    note: str | None = Field(default=None, max_length=500)


class PublishRequest(BaseModel):
    version_id: str


class ModifyRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=2000)
    scope: Literal["section", "lesson"] = "section"
    section_key: str | None = Field(default=None, max_length=60)
    selected_text: str | None = Field(default=None, max_length=8000)
    """Optional: revise only this passage inside the section."""


class ModifyResponse(BaseModel):
    """
    A PREVIEW. Nothing is saved until the admin accepts it.

    Returning the proposal rather than writing a version means a revision she
    dislikes leaves no trace in the history.
    """

    scope: str
    section_key: str | None
    original: str | None
    revised: str | None
    sections: list[dict] | None
    warnings: list[str]
    cost_usd: float


class GenerationBrief(BaseModel):
    """
    What this lesson is to be about.

    Every field optional, and any one of them is enough to generate from. The
    client's lessons are built around all of these in practice — sometimes a
    phrase of the prayer, sometimes a single Hebrew word, sometimes only
    "something for Elul" — so the brief accepts whichever the admin has rather
    than insisting on a shape.
    """

    phrase: str | None = Field(default=None, max_length=500)
    """A phrase of Nishmat, in Hebrew or transliterated."""
    hebrew_word: str | None = Field(default=None, max_length=120)
    theme: str | None = Field(default=None, max_length=400)
    psalm: str | None = Field(default=None, max_length=60)
    commentator: str | None = Field(default=None, max_length=200)
    seasonal: str | None = Field(default=None, max_length=200)
    objective: str | None = Field(default=None, max_length=1000)
    length: Literal["short", "standard", "long"] | None = None
    notes: str | None = Field(default=None, max_length=2000)

    def is_empty(self) -> bool:
        return not any(self.model_dump(exclude_none=True).values())


class GenerateRequest(BaseModel):
    note: str | None = Field(
        default=None,
        max_length=2000,
        description="Anything the teacher wants this lesson to do differently.",
    )
    brief: GenerationBrief | None = None
    """
    Replaces the brief stored on the lesson when supplied.

    Omitted means "use what is already there", which is what a plain
    Regenerate should do — not silently clear the instructions.
    """


class LessonCreate(BaseModel):
    """
    Title and number are optional.

    The composer does not ask for either — the admin attaches a recording and
    presses send. Both are derived here and shown in the editor, where they can
    be corrected in place.
    """

    title: str | None = Field(default=None, max_length=300)
    lesson_number: int | None = Field(default=None, ge=0, le=9999)
    template_id: str | None = None
    series_id: str | None = None
    source_file_ids: list[str] = Field(default_factory=list, max_length=10)
    note: str | None = Field(default=None, max_length=4000)
    """Anything the admin typed into the composer — kept for the generator."""
    brief: GenerationBrief | None = None
    """What the lesson should teach, when the admin has said so up front."""


class TranscriptMatchOut(BaseModel):
    lesson_id: str
    lesson_number: int | None
    title: str
    word_count: int
    hits: int
    matched_terms: list[str]
    evidence: str
    content_text: str | None = None
    """The complete stored lesson, only when `include_text` was asked for."""


class TranscriptSearchOut(BaseModel):
    terms: list[str]
    lessons_searched: int
    matches: int
    results: list[TranscriptMatchOut]


# ------------------------------------------------------------------ search


@router.get("/search-transcripts", response_model=TranscriptSearchOut)
async def search_transcripts(
    user: AdminDep,
    q: str = Query(min_length=2, max_length=300, description="Topic or phrase"),
    include_text: bool = Query(
        default=False, description="Return each lesson's complete stored text"
    ),
    limit: int = Query(default=100, ge=1, le=200),
) -> TranscriptSearchOut:
    """
    Search the COMPLETE text of every published lesson.

    Distinct from the chatbot's retrieval, which ranks chunks by similarity and
    returns the best handful. This matches against whole stored transcripts and
    returns EVERY lesson that qualifies — the right shape of answer for "which
    lessons did I write about Sukkot", where a top-six list is simply wrong.

    Known topics ("rosh hashana", "podeh umatzil") expand to their spelling
    variants in Hebrew and transliteration; anything else is searched literally.
    Matching folds apostrophes, hyphens and nikud, so a lesson titled
    "Podeh u’Matzil" is found by someone typing an ordinary apostrophe.
    """
    from app.services import transcript_search

    terms = transcript_search.expand(q)
    results = await transcript_search.search(terms)
    corpus = await transcript_search.load_corpus()

    shown = results[:limit]
    out: list[TranscriptMatchOut] = []
    for match in shown:
        text = None
        if include_text:
            full = await transcript_search.get_transcript(match.lesson_number)
            text = (full or {}).get("content_text")
        out.append(
            TranscriptMatchOut(
                lesson_id=match.lesson_id,
                lesson_number=match.lesson_number,
                title=match.title,
                word_count=match.word_count,
                hits=match.hits,
                matched_terms=match.matched_terms,
                evidence=match.evidence,
                content_text=text,
            )
        )

    log.info(
        "transcripts_searched", q=q, terms=len(terms), matches=len(results), by=user.id
    )
    return TranscriptSearchOut(
        terms=terms,
        lessons_searched=len(corpus),
        matches=len(results),
        results=out,
    )


# --------------------------------------------------------------------- list


@router.get("", response_model=list[LessonSummary])
async def list_lessons(
    user: AdminDep,
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    needs_review: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[LessonSummary]:
    filters: dict[str, str] = {"deleted_at": "is.null"}

    if status_filter:
        wanted = [s.strip() for s in status_filter.split(",") if s.strip()]
        invalid = set(wanted) - set(_VALID_STATUSES)
        if invalid:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Unknown status: {', '.join(sorted(invalid))}",
            )
        filters["status"] = f"in.({','.join(wanted)})"

    if needs_review is not None:
        filters["needs_review"] = f"is.{str(needs_review).lower()}"

    if q:
        # PostgREST `or=` with ilike across the fields an admin would search.
        escaped = q.replace(",", " ").replace("(", "").replace(")", "")
        filters["or"] = (
            f"(title.ilike.*{escaped}*,"
            f"transliteration.ilike.*{escaped}*,"
            f"hebrew_phrase.ilike.*{escaped}*)"
        )

    rows = await supabase.service().select(
        "lessons",
        columns=LESSON_COLUMNS,
        filters=filters,
        order="lesson_number.asc.nullslast",
        limit=limit,
        offset=offset,
    )
    return [_to_summary(row) for row in rows]


_VALID_STATUSES = {
    "draft", "processing", "generated", "review",
    "approved", "published", "archived", "failed",
}


# -------------------------------------------------------------------- create


@router.post("", response_model=LessonDetail, status_code=status.HTTP_201_CREATED)
async def create_lesson(payload: LessonCreate, user: AdminDep) -> LessonDetail:
    """
    Create an empty lesson and attach any already-uploaded source files.

    Deliberately creates NO version. A lesson with no content is a `draft`
    with nothing to publish — the first version arrives when the AI generates
    one, or when the admin writes it by hand.
    """
    db = supabase.service()

    lesson_number = payload.lesson_number
    if lesson_number is None:
        lesson_number = await _next_lesson_number(db)

    if lesson_number is not None:
        clash = await db.select(
            "lessons",
            columns="id, title",
            filters={
                "lesson_number": f"eq.{lesson_number}",
                "deleted_at": "is.null",
            },
            single=True,
        )
        if clash:
            if payload.lesson_number is None:
                # We suggested it, so a clash is our problem, not the admin's.
                lesson_number = None
            else:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Lesson #{lesson_number} already exists "
                    f"(\"{clash['title']}\"). Choose a different number.",
                )

    template_id = payload.template_id
    if template_id is None:
        default = await db.select(
            "lesson_templates",
            columns="id",
            filters={"is_default": "is.true"},
            single=True,
        )
        template_id = default["id"] if default else None

    series_id = payload.series_id
    if series_id is None:
        series = await db.select("series", columns="id", limit=1)
        series_id = series[0]["id"] if series else None

    brief = _brief_dict(payload.brief)

    title = (payload.title or "").strip()
    if not title:
        title = await _suggest_title(db, payload.source_file_ids)
    if title == "Untitled lesson" and brief:
        # A brief-driven lesson has no file to take a name from, but it does
        # have the admin's own words for what it is about — a far better
        # placeholder than "Untitled" for finding it again in the list.
        title = _title_from_brief(payload.brief) or title

    created = await db.insert(
        "lessons",
        {
            "title": title,
            "lesson_number": lesson_number,
            "sequence_position": lesson_number,
            "template_id": template_id,
            "series_id": series_id,
            "status": "draft",
            "created_by": user.id,
            "generation_brief": brief,
        },
    )
    lesson = created[0] if isinstance(created, list) else created

    # Link any files uploaded before the lesson existed — the admin uploads
    # first and names the lesson afterwards, which is the natural order.
    for file_id in payload.source_file_ids:
        try:
            await db.update(
                "source_files",
                {"id": f"eq.{file_id}"},
                {"lesson_id": lesson["id"]},
                returning=False,
            )
        except supabase.SupabaseError:
            log.warning(
                "source_file_link_failed", lesson_id=lesson["id"], file_id=file_id
            )

    log.info("lesson_created", lesson_id=lesson["id"], by=user.id)
    return await get_lesson(lesson["id"], user)


def _brief_dict(brief: GenerationBrief | None) -> dict | None:
    """The brief as stored — omitting empty fields so a blank form stays null."""
    if brief is None:
        return None
    data = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in brief.model_dump(exclude_none=True).items()
        if not (isinstance(value, str) and not value.strip())
    }
    return data or None


def _title_from_brief(brief: GenerationBrief | None) -> str | None:
    if brief is None:
        return None
    for candidate in (brief.phrase, brief.hebrew_word, brief.theme, brief.objective):
        if candidate and candidate.strip():
            return candidate.strip()[:120]
    return None


async def _next_lesson_number(db) -> int | None:
    """The next free number in the series, so the admin never has to look it up."""
    rows = await db.select(
        "lessons",
        columns="lesson_number",
        filters={"deleted_at": "is.null", "lesson_number": "not.is.null"},
        order="lesson_number.desc",
        limit=1,
    )
    if not rows:
        return 1
    highest = rows[0].get("lesson_number")
    return highest + 1 if isinstance(highest, int) else None


async def _suggest_title(db, source_file_ids: list[str]) -> str:
    """Name the lesson from its source text, falling back to the filename."""
    from app.services.ingestion.titling import suggest_title

    for file_id in source_file_ids:
        row = await db.select(
            "source_files",
            columns="original_filename, extracted_text, processing_status",
            filters={"id": f"eq.{file_id}"},
            single=True,
        )
        if not row:
            continue

        fallback = (row.get("original_filename") or "Untitled lesson").rsplit(".", 1)[0]
        if row.get("extracted_text"):
            return suggest_title(row["extracted_text"], fallback=fallback)
        return fallback

    return "Untitled lesson"


# ---------------------------------------------------------------- read / edit


@router.get("/{lesson_id}", response_model=LessonDetail)
async def get_lesson(lesson_id: str, user: AdminDep) -> LessonDetail:
    db = supabase.service()
    row = await db.select(
        "lessons",
        columns=LESSON_COLUMNS,
        filters={"id": f"eq.{lesson_id}", "deleted_at": "is.null"},
        single=True,
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That lesson was not found.")

    current = None
    if row.get("current_version_id"):
        current = await db.select(
            "lesson_versions",
            columns=(
                "id, version_number, content, content_text, word_count, origin, "
                "modification_instruction, quality_report, model_metadata, "
                "created_at"
            ),
            filters={"id": f"eq.{row['current_version_id']}"},
            single=True,
        )

    return LessonDetail(**_to_summary(row).model_dump(), **{
        "series_id": row.get("series_id"),
        "template_id": row.get("template_id"),
        "translation": row.get("translation"),
        "summary": row.get("summary"),
        "current_version_id": row.get("current_version_id"),
        "published_version_id": row.get("published_version_id"),
        "created_at": row["created_at"],
        "current_version": current,
        "generation_brief": row.get("generation_brief"),
    })


@router.patch("/{lesson_id}", response_model=LessonSummary)
async def update_lesson(
    lesson_id: str, payload: LessonUpdate, user: AdminDep
) -> LessonSummary:
    """Metadata only. Lesson *content* changes go through a new version."""
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update.")

    rows = await supabase.service().update(
        "lessons", {"id": f"eq.{lesson_id}", "deleted_at": "is.null"}, changes
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That lesson was not found.")

    log.info("lesson_updated", lesson_id=lesson_id, fields=sorted(changes), by=user.id)
    return _to_summary(rows[0] if isinstance(rows, list) else rows)


@router.delete(
    "/{lesson_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # 204 carries no body. `from __future__ import annotations` turns the
    # `-> None` hint into a string, which FastAPI resolves to a response model
    # and then rejects for a 204 — so say it explicitly.
    response_model=None,
    response_class=Response,
)
async def delete_lesson(lesson_id: str, user: AdminDep) -> None:
    """
    Soft delete, and withdraw from the index.

    Soft, because the client's lessons are years of work and a mis-click must
    be recoverable.
    """
    from datetime import datetime, timezone

    db = supabase.service()
    rows = await db.update(
        "lessons",
        {"id": f"eq.{lesson_id}", "deleted_at": "is.null"},
        {
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "published_version_id": None,
            "status": "archived",
        },
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That lesson was not found.")

    await db.delete("lesson_chunks", {"lesson_id": f"eq.{lesson_id}"})
    log.info("lesson_deleted", lesson_id=lesson_id, by=user.id)


# ------------------------------------------------------------------ versions


@router.get("/{lesson_id}/versions", response_model=list[VersionSummary])
async def list_versions(lesson_id: str, user: AdminDep) -> list[VersionSummary]:
    db = supabase.service()

    lesson = await db.select(
        "lessons",
        columns="id, current_version_id, published_version_id",
        filters={"id": f"eq.{lesson_id}"},
        single=True,
    )
    if not lesson:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That lesson was not found.")

    rows = await db.select(
        "lesson_versions",
        columns=(
            "id, version_number, origin, modification_instruction, "
            "word_count, created_at, created_by"
        ),
        filters={"lesson_id": f"eq.{lesson_id}"},
        order="version_number.desc",
    )

    return [
        VersionSummary(
            **row,
            is_published=row["id"] == lesson.get("published_version_id"),
            is_current=row["id"] == lesson.get("current_version_id"),
        )
        for row in rows
    ]


@router.get("/{lesson_id}/versions/{version_id}")
async def get_version(lesson_id: str, version_id: str, user: AdminDep) -> dict:
    row = await supabase.service().select(
        "lesson_versions",
        columns="*",
        filters={"id": f"eq.{version_id}", "lesson_id": f"eq.{lesson_id}"},
        single=True,
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That version was not found.")
    return row


@router.post("/{lesson_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_version(
    lesson_id: str, payload: VersionCreate, user: AdminDep
) -> dict:
    """
    Save a manual edit as a new version.

    Does NOT publish it. `published_version_id` is untouched, so learners keep
    seeing whatever was published until the admin says otherwise.
    """
    sections = payload.content.get("sections")
    if not isinstance(sections, list) or not sections:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A lesson needs at least one section."
        )

    db = supabase.service()
    lesson = await db.select(
        "lessons",
        columns="id, current_version_id, status",
        filters={"id": f"eq.{lesson_id}", "deleted_at": "is.null"},
        single=True,
    )
    if not lesson:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That lesson was not found.")

    content_text = "\n\n".join(
        (section.get("body") or "").strip() for section in sections
    ).strip()

    # One call: allocate the number, insert, and repoint the lesson — all in a
    # single transaction. Splitting those across requests left a race where two
    # simultaneous saves were handed the same version number and one was lost.
    version = await db.rpc(
        "create_lesson_version",
        {
            "p_lesson_id": lesson_id,
            "p_content": {"sections": sections},
            "p_content_text": content_text,
            "p_word_count": len(content_text.split()),
            "p_origin": "manual_edit",
            "p_instruction": payload.note,
            "p_created_by": user.id,
        },
    )
    if isinstance(version, list):
        version = version[0] if version else None
    if not version:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "We couldn't save that version."
        )

    log.info(
        "version_created",
        lesson_id=lesson_id,
        version=version["version_number"],
        origin="manual_edit",
        by=user.id,
    )
    return version


@router.post("/{lesson_id}/versions/{version_id}/restore", status_code=201)
async def restore_version(lesson_id: str, version_id: str, user: AdminDep) -> dict:
    """
    Bring an old version back as a NEW version.

    Never rewinds history — restoring version 2 creates version 5 with version
    2's content, so the intervening work is still there.
    """
    db = supabase.service()
    source = await db.select(
        "lesson_versions",
        columns="id, content, content_text, word_count, version_number",
        filters={"id": f"eq.{version_id}", "lesson_id": f"eq.{lesson_id}"},
        single=True,
    )
    if not source:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That version was not found.")

    return await create_version(
        lesson_id,
        VersionCreate(
            content=source["content"],
            note=f"Restored from version {source['version_number']}",
        ),
        user,
    )


# ------------------------------------------------------------------ generate


@router.post("/{lesson_id}/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_lesson(
    lesson_id: str, payload: GenerateRequest, user: AdminDep
) -> dict:
    """
    Queue a draft.

    Returns a job id immediately — the pipeline makes several model calls and
    takes about a minute, which is far too long to hold an HTTP request open.
    The result is a new version; nothing is ever published automatically.
    """
    db = supabase.service()

    lesson = await db.select(
        "lessons",
        columns="id, status, generation_brief",
        filters={"id": f"eq.{lesson_id}", "deleted_at": "is.null"},
        single=True,
    )
    if not lesson:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That lesson was not found.")

    # A brief sent with this request replaces the stored one; sending none keeps
    # whatever is there, so a plain Regenerate does not quietly wipe it.
    brief = _brief_dict(payload.brief)
    if payload.brief is not None:
        await db.update(
            "lessons", {"id": f"eq.{lesson_id}"}, {"generation_brief": brief},
            returning=False,
        )
    else:
        brief = lesson.get("generation_brief")

    # A lesson needs SOMETHING to work from: its own recorded material, or an
    # instruction about what to teach. Either is enough on its own — requiring
    # an uploaded file, as this used to, made a lesson built around a phrase of
    # the prayer impossible to ask for.
    ready = await db.select(
        "source_files",
        columns="id, role",
        filters={
            "lesson_id": f"eq.{lesson_id}",
            "processing_status": "eq.completed",
            "role": "eq.lesson_source",
        },
        limit=1,
    )
    if not ready and not brief:
        pending = await db.select(
            "source_files",
            columns="id",
            filters={
                "lesson_id": f"eq.{lesson_id}",
                "processing_status": "in.(pending,processing)",
            },
            limit=1,
        )
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This lesson is still reading its uploaded material — try again in a "
            "moment."
            if pending
            else "This lesson has nothing to work from yet. Upload a recording or "
            "a document, or tell it what to teach — a Nishmat phrase, a theme, a "
            "Psalm — and attach any pages you want it to use.",
        )

    # Refuse to start while a reference page is still being read.
    #
    # The admin attaches pages and presses Generate — that is the whole point of
    # attaching them. Reading a photographed page takes the better part of a
    # minute, and generating in the meantime produces a draft written without
    # the very material they just supplied, with nothing to show that it was
    # missed. Better to make them wait a moment and say why.
    unread = await db.select(
        "source_files",
        columns="id, original_filename",
        filters={
            "lesson_id": f"eq.{lesson_id}",
            "role": "eq.reference",
            "processing_status": "in.(pending,processing)",
        },
        limit=3,
    )
    if unread:
        names = ", ".join(f'"{row["original_filename"]}"' for row in unread)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Still reading {names}. Give it a moment and generate again, or "
            f"remove the page if it is not needed — generating now would write "
            f"the lesson without it.",
        )

    # Refuse to queue a second run while one is already in flight — it would
    # double the cost and produce two drafts racing to save.
    running = await db.select(
        "jobs",
        columns="id, status",
        filters={
            "lesson_id": f"eq.{lesson_id}",
            "type": "eq.generate_lesson",
            "status": "in.(queued,running)",
        },
        limit=1,
    )
    if running:
        return {"job_id": running[0]["id"], "already_running": True}

    job_id = await queue.enqueue(
        queue.JobType.GENERATE_LESSON,
        {"lesson_id": lesson_id, "note": payload.note, "brief": brief},
        lesson_id=lesson_id,
        created_by=user.id,
        max_attempts=2,
    )

    log.info("generation_queued", lesson_id=lesson_id, job_id=job_id, by=user.id)
    return {"job_id": job_id, "already_running": False}


# -------------------------------------------------------------------- modify


@router.post("/{lesson_id}/modify", response_model=ModifyResponse)
async def modify_lesson(
    lesson_id: str, payload: ModifyRequest, user: AdminDep
) -> ModifyResponse:
    """
    Ask the AI to revise a passage, or the whole lesson.

    Returns a PROPOSAL. It does not create a version and does not publish —
    the admin sees a diff and decides. Accepting it goes through the normal
    `POST /versions` path, so an AI revision and a hand edit are stored the
    same way.

    Synchronous rather than queued: a scoped edit is a single call of a few
    seconds, and the admin is sitting there waiting to see the diff. Queuing it
    would add more latency than the work takes.
    """
    db = supabase.service()

    lesson = await db.select(
        "lessons",
        columns="id, title, template_id, current_version_id",
        filters={"id": f"eq.{lesson_id}", "deleted_at": "is.null"},
        single=True,
    )
    if not lesson:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That lesson was not found.")
    if not lesson.get("current_version_id"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This lesson has no content yet. Generate or write a draft first.",
        )

    version = await db.select(
        "lesson_versions",
        columns="content",
        filters={"id": f"eq.{lesson['current_version_id']}"},
        single=True,
    )
    sections = ((version or {}).get("content") or {}).get("sections") or []
    if not sections:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This lesson has no sections to revise."
        )

    template = await _load_template(db, lesson.get("template_id"))

    try:
        if payload.scope == "lesson":
            result = await modification_service.revise_lesson(
                sections=sections,
                instruction=payload.instruction,
                template=template,
            )
            log.info(
                "lesson_modified",
                lesson_id=lesson_id,
                scope="lesson",
                by=user.id,
            )
            return ModifyResponse(
                scope="lesson",
                section_key=None,
                original=None,
                revised=None,
                sections=result.sections,
                warnings=result.warnings,
                cost_usd=round(result.usage.estimated_cost if result.usage else 0, 6),
            )

        if not payload.section_key:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Tell us which section to revise.",
            )

        revision = await modification_service.revise_section(
            sections=sections,
            section_key=payload.section_key,
            instruction=payload.instruction,
            template=template,
            lesson_title=lesson.get("title"),
            selected_text=payload.selected_text,
        )

        if not revision.changed:
            revision.warnings.append(
                "The revision came back unchanged — try being more specific."
            )

        log.info(
            "lesson_modified",
            lesson_id=lesson_id,
            scope="section",
            section=payload.section_key,
            by=user.id,
        )
        return ModifyResponse(
            scope="section",
            section_key=revision.section_key,
            original=revision.original,
            revised=revision.revised,
            sections=None,
            warnings=revision.warnings,
            cost_usd=round(revision.usage.estimated_cost if revision.usage else 0, 6),
        )

    except modification_service.ModificationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None


async def _load_template(db, template_id: str | None) -> dict:
    filters = {"id": f"eq.{template_id}"} if template_id else {"is_default": "is.true"}
    template = await db.select(
        "lesson_templates",
        columns="id, name, sections, style_guide, formatting_rules, constraints",
        filters=filters,
        single=True,
    )
    if not template:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No lesson format is configured. Set one up under Lesson format.",
        )
    return template


# ------------------------------------------------------------------- publish


@router.post("/{lesson_id}/publish", response_model=LessonSummary)
async def publish_lesson(
    lesson_id: str, payload: PublishRequest, user: AdminDep
) -> LessonSummary:
    try:
        row = await publishing_service.publish(
            lesson_id, payload.version_id, actor_id=user.id
        )
    except publishing_service.PublishError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return _to_summary(row)


@router.post("/{lesson_id}/unpublish", response_model=LessonSummary)
async def unpublish_lesson(lesson_id: str, user: AdminDep) -> LessonSummary:
    try:
        row = await publishing_service.unpublish(lesson_id, actor_id=user.id)
    except publishing_service.PublishError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    return _to_summary(row)


# ------------------------------------------------------------------- helpers


def _to_summary(row: dict) -> LessonSummary:
    return LessonSummary(
        id=row["id"],
        title=row.get("title") or "Untitled lesson",
        lesson_number=row.get("lesson_number"),
        hebrew_phrase=row.get("hebrew_phrase"),
        transliteration=row.get("transliteration"),
        status=row.get("status", "draft"),
        needs_review=bool(row.get("needs_review")),
        review_notes=row.get("review_notes"),
        published_at=row.get("published_at"),
        updated_at=row["updated_at"],
        # The signal the admin most needs on a list: edited since it went live.
        has_unpublished_changes=bool(
            row.get("published_version_id")
            and row.get("current_version_id")
            and row["current_version_id"] != row["published_version_id"]
        ),
    )
