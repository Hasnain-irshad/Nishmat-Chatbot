"""
The lesson generation pipeline.

    brief and/or source text
       │
       ├─ 0. RETRIEVE     the sources this lesson needs        (no model to decide)
       ├─ 1. ANALYSE      what is actually in this material    (cheap model, temp 0.2)
       ├─ 2. ASSEMBLE     template + style + series + refs     (no model at all)
       ├─ 3. WRITE        the lesson                           (strong model, temp 0.85)
       ├─ 4. GROUND       every quote against the stored text  (no model at all)
       └─ 5. CHECK        fresh reader, adversarial            (cheap model, temp 0)
                │
                └─ FAIL → rewrite ONCE with the issues → then stop, whatever happens

Each stage is persisted, so when a lesson comes out wrong you can see which
stage went wrong rather than guessing at one opaque prompt.

Stage 0 is the one the client's requirement turns on. The generator used to see
nothing but an uploaded transcript, which meant a lesson about a phrase of the
prayer was written from whatever the recording happened to say about it, and
any Hebrew beyond that was recalled rather than read. It now retrieves the
prayer, the Psalms it quotes, the teacher's reference material and any pages
she photographed, each in its own labelled slot.

Stage 4 is deterministic on purpose. Asking a model whether a verse is real
gets a confident yes, because it recognises the verse from training. Asking the
database whether the verse is in the corpus we supplied is a different question
and the only one that catches the failure.

The retry is capped at one deliberately. An automatic regeneration loop chasing
a PASS would burn a fixed budget in minutes and, on a genuinely thin source,
would never converge. After one attempt the draft goes to the admin with its
problems listed — a human reading it is the real quality gate.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.db import supabase
from app.llm import prompt_builder
from app.llm.provider import get_provider
from app.llm.types import BudgetExceeded, LLMError, Usage
from app.logging import get_logger
from app.models.analysis import StructuredAnalysis, analysis_json_schema
from app.services import grounding_service, reference_service
from app.services.reference_service import LessonBrief, ReferenceBundle

log = get_logger("services.generation")


class GenerationError(Exception):
    """Generation failed. The message is safe to show the admin."""


@dataclass
class GenerationResult:
    sections: list[dict]
    content_text: str
    word_count: int
    analysis: StructuredAnalysis
    quality: dict
    model_metadata: dict = field(default_factory=dict)
    attempts: int = 1
    references: dict = field(default_factory=dict)
    """Which sources were used — recorded on the version, shown to the admin."""


# ================================================================ stage 1 ==


async def analyse(
    source_text: str | None,
    *,
    hint: str | None = None,
    lesson_id: str | None = None,
    brief: LessonBrief | None = None,
    references: ReferenceBundle | None = None,
) -> tuple[StructuredAnalysis, Usage]:
    """
    Read the dossier and report what is in it. No writing happens here.

    A lesson can be built from a transcript, from retrieved references, or from
    both. What it can never be built from is nothing — so the check below is on
    the dossier as a whole rather than on the transcript alone, which is what
    made a brief-driven lesson impossible before.
    """
    transcript_words = len((source_text or "").split())
    reference_words = sum(
        len(item.text.split()) for item in (references.all_items() if references else [])
    )

    if transcript_words < 25 and reference_words < 60:
        raise GenerationError(
            "There isn't enough material to build a lesson from. Upload a "
            "recording or a document, name a Nishmat phrase or a theme to teach, "
            "or attach a page from a book."
        )

    provider = get_provider()
    messages = prompt_builder.build_analysis_messages(
        source_text if transcript_words >= 25 else None,
        hint=hint,
        brief=brief,
        references=references,
    )

    completion = await provider.complete(
        messages,
        operation="analysis",
        temperature=0.2,  # reading, not writing
        json_schema=analysis_json_schema(),
    )

    if not completion.parsed:
        raise GenerationError("We couldn't make sense of that source material.")

    try:
        analysis = StructuredAnalysis.model_validate(completion.parsed)
    except Exception as exc:
        log.error("analysis_validation_failed", error=str(exc))
        raise GenerationError("The analysis of that source came back malformed.") from exc

    risks = analysis.fabrication_risks()
    if risks:
        # Not an error — the model flagged its own recall honestly, which is the
        # system working. Recorded so the admin can see what was excluded.
        log.info("analysis_excluded_unsourced", lesson_id=lesson_id, count=len(risks))

    return analysis, completion.usage


# ================================================================ stage 2 ==


async def assemble_context(
    analysis: StructuredAnalysis,
    *,
    template: dict,
    lesson_id: str | None,
    lesson_number: int | None,
    source_text: str | None,
    admin_note: str | None,
    brief: LessonBrief | None = None,
    references: ReferenceBundle | None = None,
) -> prompt_builder.GenerationContext:
    """Gather everything the writer needs. Deterministic — no model calls."""
    db = supabase.service()

    style_examples = await _retrieve_style_examples(analysis)
    series = await _series_context(db, lesson_number, exclude_lesson_id=lesson_id)
    avoid = await _recent_signature_phrases(db, exclude_lesson_id=lesson_id)

    return prompt_builder.GenerationContext(
        analysis=analysis,
        template=template,
        style_examples=style_examples,
        previous_lesson=series.previous,
        lesson_number=lesson_number,
        admin_note=admin_note,
        source_text=source_text,
        avoid_phrases=avoid,
        brief=brief,
        references=references,
        series=series,
    )


async def _retrieve_style_examples(analysis: StructuredAnalysis) -> list[dict]:
    """
    Find two of her own lessons closest in theme to this one.

    Falls back to any approved examples if the embedding lookup is unavailable —
    showing her writing matters far more than showing the *closest* writing.
    """
    db = supabase.service()
    provider = get_provider()

    try:
        query = f"{analysis.central_theme}. {' '.join(analysis.key_concepts[:5])}"
        embeddings = await provider.embed([query], operation="embedding")
        rows = await db.rpc(
            "match_style_examples",
            {"query_embedding": embeddings.vectors[0], "match_count": 8},
        )
        if rows:
            return prompt_builder.pick_style_examples(rows, count=2)
    except (LLMError, supabase.SupabaseError) as exc:
        log.warning("style_retrieval_failed", error=str(exc))

    rows = await db.select(
        "style_examples",
        columns="title, source_text, final_text, tags",
        filters={"is_approved": "is.true"},
        limit=8,
    )
    return prompt_builder.pick_style_examples(rows, count=2)


RECENT_LESSON_WINDOW = 4


async def _series_context(
    db, lesson_number: int | None, *, exclude_lesson_id: str | None = None
) -> prompt_builder.SeriesContext:
    """
    Where this lesson sits in the series.

    Three things, where there used to be one title:

      * the last few lessons WITH what each was about, so "don't repeat
        yourself" is checkable rather than aspirational. `lessons.summary`
        already holds the central theme the analysis stage extracted, so this
        costs one query and no model call;
      * the next lesson when it already exists, so this one can stop at its
        edge instead of spending its material;
      * drafts as well as published lessons. A lesson written last Tuesday and
        not yet published is still a lesson the reader will have, and the
        published-only filter meant the generator could not see it and would
        happily cover the same ground twice.
    """
    context = prompt_builder.SeriesContext()
    if lesson_number is None:
        return context

    columns = "id, lesson_number, title, transliteration, hebrew_phrase, summary, status"
    ready = "in.(generated,review,approved,published)"

    previous = await db.select(
        "lessons",
        columns=columns,
        filters={
            "lesson_number": f"lt.{lesson_number}",
            "status": ready,
            "deleted_at": "is.null",
        },
        order="lesson_number.desc",
        limit=RECENT_LESSON_WINDOW,
    )
    context.recent = [
        row for row in (previous or []) if row.get("id") != exclude_lesson_id
    ]

    upcoming = await db.select(
        "lessons",
        columns=columns,
        filters={
            "lesson_number": f"gt.{lesson_number}",
            "deleted_at": "is.null",
        },
        order="lesson_number.asc",
        limit=1,
    )
    for row in upcoming or []:
        if row.get("id") != exclude_lesson_id:
            context.next_lesson = row
        break

    return context


SIGNATURE_LINE = re.compile(r"^[A-Z][^.!?]{8,60}[.!?]$")


async def _recent_signature_phrases(db, *, exclude_lesson_id: str | None) -> list[str]:
    """
    Distinctive short lines from recent lessons, so they are not reused.

    Her style leans on short standalone lines for emphasis. Left unchecked the
    model recycles the strongest ones from whichever examples it was shown —
    "Maybe for weeks. Maybe for months." belongs to the lesson it was written
    for, and reusing it is exactly what makes output feel machine-made.
    """
    try:
        rows = await db.select(
            "lesson_versions",
            columns="lesson_id, content_text, created_at",
            order="created_at.desc",
            limit=10,
        )
    except supabase.SupabaseError:
        return []

    phrases: list[str] = []
    for row in rows:
        if exclude_lesson_id and row.get("lesson_id") == exclude_lesson_id:
            continue
        for line in (row.get("content_text") or "").splitlines():
            line = line.strip()
            if SIGNATURE_LINE.match(line) and len(line.split()) <= 9:
                phrases.append(line)

    seen: set[str] = set()
    unique = []
    for phrase in phrases:
        key = phrase.lower()
        if key not in seen:
            seen.add(key)
            unique.append(phrase)
    return unique[:12]


# ================================================================ stage 3 ==


async def write_lesson(
    context: prompt_builder.GenerationContext, *, feedback: list[str] | None = None
) -> tuple[list[dict], Usage]:
    provider = get_provider()
    messages = prompt_builder.build_generation_messages(context)

    if feedback:
        messages.append(
            prompt_builder.Message(
                role="user",
                content=(
                    "That draft had problems. Rewrite the whole lesson, fixing "
                    "these and changing nothing else:\n\n"
                    + "\n".join(f"- {item}" for item in feedback)
                ),
            )
        )

    completion = await provider.complete(
        messages,
        operation="generation",
        # High enough for the writing to breathe; the schema and the source
        # constraints are what keep it honest, not a low temperature.
        temperature=0.85,
        json_schema=prompt_builder.lesson_json_schema(context.template),
    )

    if not completion.parsed:
        raise GenerationError("The lesson came back in an unreadable form.")

    sections = completion.parsed.get("sections") or []
    if not sections:
        raise GenerationError("The model returned an empty lesson.")

    return _normalise_sections(sections, context.template), completion.usage


def _normalise_sections(sections: list[dict], template: dict) -> list[dict]:
    """
    Put the sections into template order and mark direction correctly.

    Order comes from the template, not from the model — the model gets the
    content right far more reliably than it gets the ordering right.
    """
    order_by_key = {
        section["key"]: section.get("order", index)
        for index, section in enumerate(template.get("sections", []), start=1)
    }
    rtl_keys = set((template.get("formatting_rules") or {}).get("rtl_blocks") or [])

    cleaned: list[dict] = []
    for index, section in enumerate(sections):
        body = (section.get("body") or "").strip()
        if not body:
            continue
        key = section.get("key") or f"body_{index + 1}"

        direction = section.get("dir") or "ltr"
        if key in rtl_keys:
            direction = "rtl"

        cleaned.append(
            {
                "key": key,
                "title": section.get("title") or None,
                "body": body,
                "dir": direction,
                "order": order_by_key.get(key, 100 + index),
            }
        )

    cleaned.sort(key=lambda s: s["order"])
    for position, section in enumerate(cleaned, start=1):
        section["order"] = position
    return cleaned


# ================================================================ stage 4 ==


async def check_quality(
    sections: list[dict],
    *,
    analysis: StructuredAnalysis,
    template: dict,
    source_text: str | None,
    references: ReferenceBundle | None = None,
) -> tuple[dict, Usage | None]:
    """
    Deterministic checks first, then a fresh model read.

    The cheap checks catch the boring failures — a missing section, altered
    Hebrew — for nothing. Only what code cannot judge is sent to a model.
    """
    lesson_text = "\n\n".join(section["body"] for section in sections)

    reference_items = references.all_items() if references else []
    source_words = len((source_text or "").split()) + sum(
        len(item.text.split()) for item in reference_items
    )

    issues = _mechanical_issues(
        sections,
        analysis=analysis,
        template=template,
        source_words=source_words,
    )

    # Grounding: every quotation traced back to something we actually supplied.
    try:
        issues.extend(
            await grounding_service.check(
                sections=sections,
                reference_texts=[item.text for item in reference_items],
                source_text=source_text,
                allowed_psalms=_allowed_psalms(references),
            )
        )
    except Exception:
        # A grounding check that throws must never lose a finished lesson.
        log.exception("grounding_check_failed")

    provider = get_provider()
    usage = None
    report: dict[str, Any] = {"verdict": "PASS", "checks": {}, "issues": [], "summary": ""}

    try:
        messages = prompt_builder.build_quality_messages(
            lesson_text=lesson_text,
            analysis=analysis,
            template=template,
            source_text=source_text,
            references=references,
        )
        completion = await provider.complete(
            messages,
            operation="quality",
            temperature=0.0,
            json_schema=prompt_builder.quality_json_schema(),
        )
        usage = completion.usage
        if completion.parsed:
            report = completion.parsed
    except (LLMError, BudgetExceeded) as exc:
        # A failed check must not lose a good lesson — flag it and move on.
        log.warning("quality_check_failed", error=str(exc))
        report["summary"] = "The automatic quality check could not run."
        report.setdefault("issues", []).append(
            {
                "severity": "low",
                "section": None,
                "message": "The automatic quality check did not run.",
                "suggestion": "Please read this draft through carefully.",
            }
        )

    report.setdefault("issues", []).extend(issues)

    # Mechanical findings can override a model that was too generous.
    if any(issue["severity"] == "high" for issue in report["issues"]):
        report["verdict"] = "FAIL"
    elif report.get("verdict") == "PASS" and report["issues"]:
        report["verdict"] = "WARN"

    return report, usage


def _allowed_psalms(references: ReferenceBundle | None) -> set[int]:
    """
    Which chapters of Tehillim the writer was actually shown.

    A citation of anything else is being recalled rather than read, which is
    the precise thing the client asked us to stop.
    """
    if not references:
        return set()

    numbers: set[int] = set()
    for item in references.scripture:
        psalm = (item.metadata or {}).get("psalm")
        if isinstance(psalm, int):
            numbers.add(psalm)
        elif isinstance(psalm, str) and psalm.isdigit():
            numbers.add(int(psalm))
    return numbers


def _mechanical_issues(
    sections: list[dict],
    *,
    analysis: StructuredAnalysis,
    template: dict,
    source_words: int = 0,
) -> list[dict]:
    issues: list[dict] = []
    present = {section["key"] for section in sections}

    # ---- padding -------------------------------------------------------
    #
    # Telling the model not to pad a thin source does not work reliably: a
    # 185-word source still produced 561 words. Anything beyond roughly three
    # times the source has to be invented, so this is checked in code rather
    # than asked for in a prompt.
    words = sum(len(section["body"].split()) for section in sections)
    if source_words >= 40 and words > source_words * 3.5:
        issues.append(
            {
                "severity": "high",
                "section": None,
                "message": (
                    f"The lesson is {words} words from a {source_words}-word "
                    f"source. Most of it cannot have come from the material."
                ),
                "suggestion": (
                    "Check for invented content. A thin source should produce a "
                    "short lesson."
                ),
            }
        )

    # ---- rhythm --------------------------------------------------------
    #
    # Line length is the signature of this author's style, so it is measured
    # rather than left to a model's judgement.
    lines = [
        line.strip()
        for section in sections
        if not section["key"].startswith(("series_title", "lesson_number", "hebrew"))
        for line in section["body"].splitlines()
        if line.strip()
    ]
    if len(lines) >= 12:
        short = sum(1 for line in lines if len(line.split()) <= 6)
        share = short / len(lines)
        target = (template.get("formatting_rules") or {}).get(
            "target_short_line_percentage", 40
        )
        if share < (target / 100) * 0.5:
            issues.append(
                {
                    "severity": "medium",
                    "section": None,
                    "message": (
                        f"Only {share:.0%} of lines are short, against about "
                        f"{target}% in her published lessons — the pacing reads "
                        f"as prose rather than as her voice."
                    ),
                    "suggestion": "Break the longer lines onto separate lines.",
                }
            )

    for section in template.get("sections", []):
        if section.get("required") and section["key"] not in present:
            issues.append(
                {
                    "severity": "medium",
                    "section": section["key"],
                    "message": f"The '{section.get('label', section['key'])}' section is missing.",
                    "suggestion": "Add it, or mark the section optional in the template.",
                }
            )

    # Hebrew must survive byte for byte. This is not a judgement call, so it is
    # checked in code rather than asked of a model.
    if analysis.hebrew_phrase:
        hebrew_sections = [s["body"] for s in sections if s["dir"] == "rtl"]
        combined = " ".join(hebrew_sections)
        if combined and analysis.hebrew_phrase.strip() not in combined:
            issues.append(
                {
                    "severity": "high",
                    "section": "hebrew_phrase",
                    "message": "The Hebrew does not match the source exactly.",
                    "suggestion": (
                        "Replace it with the phrase from the source, vowel points "
                        "included."
                    ),
                }
            )

    constraints = template.get("constraints") or {}
    minimum = constraints.get("min_words")
    maximum = constraints.get("max_words")
    if minimum and words < minimum * 0.6:
        issues.append(
            {
                "severity": "medium",
                "section": None,
                "message": f"The lesson is short — {words} words against a {minimum} target.",
                "suggestion": "Often correct for a thin source. Check nothing is missing.",
            }
        )
    elif maximum and words > maximum * 1.4:
        issues.append(
            {
                "severity": "low",
                "section": None,
                "message": f"The lesson is long — {words} words against a {maximum} target.",
                "suggestion": "Consider trimming the middle sections.",
            }
        )

    for phrase in (template.get("formatting_rules") or {}).get("avoid_phrases", []):
        for section in sections:
            if phrase.lower() in section["body"].lower():
                issues.append(
                    {
                        "severity": "low",
                        "section": section["key"],
                        "message": f'Contains "{phrase}", which the style guide avoids.',
                        "suggestion": "Rephrase in her own words.",
                    }
                )
                break

    return issues


# ============================================================== pipeline ==


async def generate(
    *,
    source_text: str | None = None,
    template: dict,
    lesson_id: str | None = None,
    lesson_number: int | None = None,
    admin_note: str | None = None,
    brief: LessonBrief | None = None,
    on_progress=None,
) -> GenerationResult:
    """Run the whole pipeline and return a draft, however it scored."""
    settings = get_settings()
    started = time.perf_counter()
    usages: list[Usage] = []
    brief = brief or LessonBrief()

    async def progress(stage: str, pct: int) -> None:
        if on_progress:
            await on_progress(stage, pct)

    await progress("Finding the sources", 8)
    try:
        references = await reference_service.retrieve(
            brief, lesson_id=lesson_id, source_text=source_text
        )
    except BudgetExceeded:
        raise
    except Exception as exc:
        # An empty corpus, or a retrieval that fell over, must not stop a lesson
        # that has a perfectly good transcript. Degrade to the old behaviour and
        # say so on the draft rather than failing the job.
        log.warning("reference_retrieval_failed", lesson_id=lesson_id, error=str(exc))
        references = ReferenceBundle(
            notes=["Reference retrieval failed; this lesson was written without it."]
        )

    await progress("Reading the sources", 20)
    analysis, analysis_usage = await analyse(
        source_text,
        hint=admin_note,
        lesson_id=lesson_id,
        brief=brief,
        references=references,
    )
    usages.append(analysis_usage)

    if not analysis.has_usable_content:
        raise GenerationError(
            "There isn't enough in this material to build a lesson from. "
            f"{analysis.source_coverage_notes}"
        )

    await progress("Gathering her style", 35)
    context = await assemble_context(
        analysis,
        template=template,
        lesson_id=lesson_id,
        lesson_number=lesson_number,
        source_text=source_text,
        admin_note=admin_note,
        brief=brief,
        references=references,
    )

    await progress("Writing the lesson", 50)
    sections, write_usage = await write_lesson(context)
    usages.append(write_usage)

    await progress("Checking the sources", 75)
    quality, quality_usage = await check_quality(
        sections,
        analysis=analysis,
        template=template,
        source_text=source_text,
        references=references,
    )
    if quality_usage:
        usages.append(quality_usage)

    attempts = 1
    if quality.get("verdict") == "FAIL" and settings.generation_max_auto_retries > 0:
        feedback = [
            issue["message"]
            for issue in quality.get("issues", [])
            if issue.get("severity") in ("high", "medium")
        ]
        if feedback:
            log.info("regenerating_after_fail", lesson_id=lesson_id, issues=len(feedback))
            await progress("Fixing what the check found", 85)
            try:
                sections, retry_usage = await write_lesson(context, feedback=feedback)
                usages.append(retry_usage)
                attempts = 2

                quality, retry_quality_usage = await check_quality(
                    sections,
                    analysis=analysis,
                    template=template,
                    source_text=source_text,
                    references=references,
                )
                if retry_quality_usage:
                    usages.append(retry_quality_usage)
            except (LLMError, BudgetExceeded) as exc:
                # Keep the first draft rather than losing the work entirely.
                log.warning("retry_failed", error=str(exc))

    content_text = "\n\n".join(section["body"] for section in sections)

    return GenerationResult(
        sections=sections,
        content_text=content_text,
        word_count=len(content_text.split()),
        analysis=analysis,
        quality=quality,
        attempts=attempts,
        references=references.summary(),
        model_metadata={
            "prompt_version": prompt_builder.PROMPT_VERSION,
            "llm_mode": settings.llm_mode,
            "attempts": attempts,
            "elapsed_seconds": round(time.perf_counter() - started, 1),
            "style_examples_used": len(context.style_examples),
            "brief": brief.to_dict(),
            "sources_used": references.summary(),
            "series_context": {
                "recent": [l.get("lesson_number") for l in (context.series.recent if context.series else [])],
                "next": (context.series.next_lesson or {}).get("lesson_number")
                if context.series
                else None,
            },
            "estimated_cost_usd": round(
                sum(usage.estimated_cost for usage in usages), 6
            ),
            "stages": [
                {
                    "operation": usage.operation,
                    "model": usage.model,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cost_usd": round(usage.estimated_cost, 6),
                }
                for usage in usages
            ],
        },
    )
