"""
Job handler: generate a lesson draft from its source material.

Runs in the worker because the pipeline makes three or four model calls and
takes the better part of a minute. Reports a real stage name at each step, so
the admin sees "Writing the lesson" rather than an indefinite spinner.

The draft is saved as a new version and NEVER published. Whatever the quality
check said, a person reads it before anyone else can.
"""

from __future__ import annotations

from app.db import supabase
from app.jobs import queue
from app.llm.types import BudgetExceeded, LLMError
from app.logging import get_logger
from app.services import generation_service
from app.services.reference_service import LessonBrief

log = get_logger("jobs.generate_lesson")


class Terminal(Exception):
    """A failure retrying cannot fix."""


async def run(job: queue.Job) -> dict:
    lesson_id = job.payload.get("lesson_id")
    if not lesson_id:
        raise ValueError("generate_lesson job has no lesson_id")

    db = supabase.service()

    lesson = await db.select(
        "lessons",
        columns=(
            "id, title, lesson_number, template_id, status, current_version_id, "
            "generation_brief"
        ),
        filters={"id": f"eq.{lesson_id}", "deleted_at": "is.null"},
        single=True,
    )
    if not lesson:
        raise Terminal("That lesson no longer exists.")

    template = await _load_template(db, lesson.get("template_id"))
    source_text, source_note = await _load_source(db, lesson_id)

    # The brief travels on the job when the admin just edited it, and on the
    # lesson otherwise — so a regeneration months later starts from the same
    # instructions rather than from an empty form.
    brief = LessonBrief.from_dict(
        job.payload.get("brief") or lesson.get("generation_brief")
    )

    if not source_text and brief.is_empty:
        raise Terminal(
            "This lesson has nothing to work from yet. Upload a recording or a "
            "document, or tell it what to teach — a Nishmat phrase, a theme, a "
            "Psalm — and attach any pages you want it to use."
        )

    await db.update(
        "lessons", {"id": f"eq.{lesson_id}"}, {"status": "processing"}, returning=False
    )

    async def on_progress(stage: str, pct: int) -> None:
        await queue.progress(job.id, stage, pct)

    try:
        result = await generation_service.generate(
            source_text=source_text or None,
            template=template,
            lesson_id=lesson_id,
            lesson_number=lesson.get("lesson_number"),
            admin_note=job.payload.get("note") or source_note,
            brief=brief,
            on_progress=on_progress,
        )

    except generation_service.GenerationError as exc:
        await _mark_failed(db, lesson_id, str(exc))
        raise Terminal(str(exc)) from exc

    except BudgetExceeded as exc:
        await _mark_failed(db, lesson_id, str(exc))
        raise Terminal(str(exc)) from exc

    except LLMError as exc:
        # Transient — let the queue retry.
        await _mark_failed(db, lesson_id, "The AI service didn't respond. Retrying.")
        raise

    await queue.progress(job.id, "Saving the draft", 92)

    version = await db.rpc(
        "create_lesson_version",
        {
            "p_lesson_id": lesson_id,
            "p_content": {"sections": result.sections},
            "p_content_text": result.content_text,
            "p_word_count": result.word_count,
            "p_origin": "ai_generated",
            "p_instruction": job.payload.get("note"),
            "p_analysis": result.analysis.model_dump(mode="json"),
            "p_quality": result.quality,
            "p_model_meta": result.model_metadata,
            "p_created_by": job.created_by,
        },
    )
    if isinstance(version, list):
        version = version[0] if version else None
    if not version:
        raise Terminal("The draft was generated but could not be saved.")

    analysis = result.analysis
    await db.update(
        "lessons",
        {"id": f"eq.{lesson_id}"},
        {
            # Status is 'generated', never 'published'. Publishing is a human act.
            "status": "generated",
            "hebrew_phrase": analysis.hebrew_phrase,
            "transliteration": analysis.transliteration,
            "translation": analysis.translation,
            "summary": analysis.central_theme[:2000],
            "needs_review": result.quality.get("verdict") != "PASS",
            "review_notes": _review_notes(result.quality),
        },
        returning=False,
    )

    log.info(
        "lesson_generated",
        lesson_id=lesson_id,
        version=version.get("version_number"),
        words=result.word_count,
        verdict=result.quality.get("verdict"),
        attempts=result.attempts,
        cost=result.model_metadata.get("estimated_cost_usd"),
    )

    return {
        "lesson_id": lesson_id,
        "version_id": version["id"],
        "version_number": version.get("version_number"),
        "word_count": result.word_count,
        "verdict": result.quality.get("verdict"),
        "issues": len(result.quality.get("issues", [])),
        "cost_usd": result.model_metadata.get("estimated_cost_usd"),
        "references": result.references,
        "sources": _describe_sources(result.references),
    }


def _describe_sources(references: dict) -> str | None:
    """
    Which sources the draft was written from, in words.

    Shown to the admin the moment generation finishes. Without it, a lesson
    written with no reference material at all — because the corpus never
    loaded, say — looks exactly like one written with all of it, and the only
    symptom is a draft that is quietly thinner than it should be.
    """
    parts: list[str] = []
    for key, label in (
        ("primary_text", "the Nishmat text"),
        ("scripture", "Tehillim"),
        ("interpretation", "reference material"),
        ("uploaded_pages", "your uploaded pages"),
    ):
        refs = [r for r in (references.get(key) or []) if r]
        if not refs:
            continue
        if key in ("primary_text", "scripture"):
            shown = ", ".join(dict.fromkeys(refs))[:120]
            parts.append(f"{label} ({shown})")
        else:
            parts.append(f"{label} ({len(refs)})")

    return " and ".join(parts) if parts else None


# ------------------------------------------------------------------ helpers


async def _load_template(db, template_id: str | None) -> dict:
    filters = {"id": f"eq.{template_id}"} if template_id else {"is_default": "is.true"}
    template = await db.select(
        "lesson_templates",
        columns=(
            "id, name, series_title, sections, optional_addons, style_guide, "
            "formatting_rules, constraints, signoff, version"
        ),
        filters=filters,
        single=True,
    )
    if not template:
        raise Terminal(
            "No lesson format is configured. Set one up under Lesson format first."
        )
    return template


async def _load_source(db, lesson_id: str) -> tuple[str, str | None]:
    """
    Combine the lesson's OWN material — the recording, the document she wrote.

    Reference uploads are deliberately excluded here. A photographed page of a
    commentary is not what the lesson is about; it is something to consult
    while writing it, and it travels through the reference pipeline where it
    keeps its attribution. Merging the two, as this used to, is exactly how a
    commentator's sentence ends up in the lesson as the teacher's own.
    """
    rows = await db.select(
        "source_files",
        columns="original_filename, extracted_text, kind, processing_status, extraction_metadata",
        filters={
            "lesson_id": f"eq.{lesson_id}",
            "processing_status": "eq.completed",
            "role": "eq.lesson_source",
        },
        order="created_at.asc",
    )

    parts: list[str] = []
    note: str | None = None

    for row in rows:
        text = (row.get("extracted_text") or "").strip()
        if not text:
            continue
        if len(rows) > 1:
            parts.append(f"--- {row['original_filename']} ({row['kind']}) ---")
        parts.append(text)

        metadata = row.get("extraction_metadata") or {}
        if metadata.get("transcript") and not metadata.get("manually_corrected"):
            note = (
                "This came from an audio transcript that has not been corrected by "
                "hand. Hebrew terms in it may be mis-transcribed — rely on meaning "
                "rather than exact spelling where a word looks wrong."
            )

    return "\n\n".join(parts), note


def _review_notes(quality: dict) -> str | None:
    issues = quality.get("issues") or []
    if not issues:
        return None

    order = {"high": 0, "medium": 1, "low": 2}
    issues = sorted(issues, key=lambda i: order.get(i.get("severity", "low"), 3))

    lines = []
    if quality.get("summary"):
        lines.append(quality["summary"])
    for issue in issues[:8]:
        prefix = issue.get("severity", "low").upper()
        lines.append(f"[{prefix}] {issue.get('message', '')}")
    return "\n".join(lines)[:4000]


async def _mark_failed(db, lesson_id: str, message: str) -> None:
    try:
        await db.update(
            "lessons",
            {"id": f"eq.{lesson_id}"},
            {"status": "failed", "needs_review": True, "review_notes": message[:2000]},
            returning=False,
        )
    except Exception:
        log.exception("could not mark lesson failed", lesson_id=lesson_id)
