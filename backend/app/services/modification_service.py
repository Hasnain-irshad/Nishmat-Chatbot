"""
AI revision — "make this paragraph warmer", "shorten the conclusion".

Two scopes, and the difference between them is the point:

**Scoped** — one section, revised with only its immediate neighbours as
context. The whole lesson is deliberately withheld. The token saving on a
700-word lesson is modest; the real gain is that a narrow context produces a
surgical edit instead of the model quietly rewriting three other paragraphs it
was never asked to touch.

**Whole-lesson** — the entire lesson, for instructions that genuinely span it
("make the whole thing warmer", "shorten by a fifth").

Neither ever publishes. Both create a new immutable version with
`origin = 'ai_modified'` and the admin's own words stored in
`modification_instruction`, so the history reads as a record of what she asked
for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.llm import prompt_builder
from app.llm.provider import get_provider
from app.llm.types import BudgetExceeded, LLMError, Usage
from app.logging import get_logger
from app.services.ingestion.base import has_hebrew

log = get_logger("services.modification")

# Neighbouring text sent as context. Enough for the model to match the
# surrounding voice, not so much that it starts editing it.
CONTEXT_CHARS = 1200


class ModificationError(Exception):
    """The revision could not be made. Safe to show the admin."""


@dataclass
class SectionRevision:
    section_key: str
    original: str
    revised: str
    warnings: list[str] = field(default_factory=list)
    usage: Usage | None = None

    @property
    def changed(self) -> bool:
        return self.revised.strip() != self.original.strip()


@dataclass
class LessonRevision:
    sections: list[dict]
    warnings: list[str] = field(default_factory=list)
    usage: Usage | None = None


# ================================================================= scoped ==


async def revise_section(
    *,
    sections: list[dict],
    section_key: str,
    instruction: str,
    template: dict,
    lesson_title: str | None = None,
    selected_text: str | None = None,
) -> SectionRevision:
    """
    Revise one section, or one selected passage inside it.

    `selected_text` lets the admin highlight a paragraph rather than the whole
    section. Only that passage is sent and only it is replaced — the rest of
    the section comes back byte for byte.
    """
    ordered = sorted(sections, key=lambda s: s.get("order", 0))
    index = next(
        (i for i, s in enumerate(ordered) if s.get("key") == section_key), None
    )
    if index is None:
        raise ModificationError("That section is no longer part of this lesson.")

    section = ordered[index]
    body = section.get("body") or ""

    passage = body
    if selected_text and selected_text.strip():
        if selected_text.strip() not in body:
            raise ModificationError(
                "That selection is no longer in the section — it may have been "
                "edited. Try selecting it again."
            )
        passage = selected_text.strip()

    if not passage.strip():
        raise ModificationError("There is nothing in that section to revise.")

    before = ordered[index - 1]["body"] if index > 0 else None
    after = ordered[index + 1]["body"] if index + 1 < len(ordered) else None

    messages = prompt_builder.build_modification_messages(
        passage=passage,
        instruction=instruction,
        template=template,
        before=before,
        after=after,
        section_label=section.get("title") or section_key.replace("_", " "),
        lesson_title=lesson_title,
    )

    try:
        completion = await get_provider().complete(
            messages,
            operation="modification",
            temperature=0.75,
            max_tokens=1600,
        )
    except BudgetExceeded:
        raise
    except LLMError as exc:
        raise ModificationError(f"The revision couldn't be made: {exc}") from exc

    revised_passage = _clean(completion.text)
    if not revised_passage:
        raise ModificationError("The revision came back empty.")

    # Splice a selection back into its section; otherwise replace the section.
    revised_body = (
        body.replace(passage, revised_passage, 1)
        if passage != body
        else revised_passage
    )

    return SectionRevision(
        section_key=section_key,
        original=body,
        revised=revised_body,
        warnings=_warn(passage, revised_passage),
        usage=completion.usage,
    )


# ================================================================== whole ==


async def revise_lesson(
    *, sections: list[dict], instruction: str, template: dict
) -> LessonRevision:
    messages = prompt_builder.build_whole_lesson_modification_messages(
        sections=sections, instruction=instruction, template=template
    )

    try:
        completion = await get_provider().complete(
            messages,
            operation="modification",
            temperature=0.75,
            json_schema=prompt_builder.lesson_json_schema(template),
        )
    except BudgetExceeded:
        raise
    except LLMError as exc:
        raise ModificationError(f"The revision couldn't be made: {exc}") from exc

    if not completion.parsed:
        raise ModificationError("The revision came back in an unreadable form.")

    returned = completion.parsed.get("sections") or []
    if not returned:
        raise ModificationError("The revision came back empty.")

    original_by_key = {s["key"]: s for s in sections}
    rebuilt: list[dict] = []
    warnings: list[str] = []

    for position, revised in enumerate(returned, start=1):
        key = revised.get("key")
        body = (revised.get("body") or "").strip()
        if not body:
            continue

        original = original_by_key.get(key, {})
        rebuilt.append(
            {
                "key": key or f"body_{position}",
                "title": revised.get("title") or original.get("title"),
                "body": body,
                # Direction is structural, not the model's to change.
                "dir": original.get("dir") or revised.get("dir") or "ltr",
                "order": position,
            }
        )
        if original.get("body"):
            warnings.extend(_warn(original["body"], body))

    dropped = set(original_by_key) - {s["key"] for s in rebuilt}
    if dropped:
        warnings.append(
            f"These sections were dropped: {', '.join(sorted(dropped))}. "
            f"Check that was intended before saving."
        )

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique = [w for w in warnings if not (w in seen or seen.add(w))]

    return LessonRevision(sections=rebuilt, warnings=unique, usage=completion.usage)


# ================================================================ helpers ==


def _clean(text: str) -> str:
    """
    Strip the wrappers models add despite being told not to.

    Asking for "only the revised text" is right, but not reliable — a leading
    "Here's the revised passage:" or surrounding quotes would otherwise be
    spliced straight into the lesson.
    """
    cleaned = text.strip()

    for opener in (
        "here's the revised",
        "here is the revised",
        "revised passage:",
        "revised:",
    ):
        if cleaned.lower().startswith(opener):
            _, _, rest = cleaned.partition("\n")
            cleaned = rest.strip() or cleaned

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    # Only unwrap quotes that enclose the whole passage.
    if len(cleaned) > 2 and cleaned[0] in "\"“" and cleaned[-1] in "\"”":
        if cleaned.count('"') <= 2:
            cleaned = cleaned[1:-1]

    # Models emit markdown hard-breaks — two trailing spaces on a line. The
    # lesson body is plain text where the newline already IS the break, so
    # those would be stored as invisible trailing whitespace.
    cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines())

    # Collapse runs of blank lines to a single blank line, which is what her
    # paragraph spacing actually is.
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")

    return cleaned.strip()


def _warn(original: str, revised: str) -> list[str]:
    """
    Cheap deterministic checks on a revision.

    These cost nothing and catch the two failures that matter: Hebrew being
    silently altered, and a revision that quietly doubles in length.
    """
    warnings: list[str] = []

    if has_hebrew(original):
        original_hebrew = _hebrew_runs(original)
        revised_hebrew = _hebrew_runs(revised)
        missing = original_hebrew - revised_hebrew
        if missing:
            warnings.append(
                "The Hebrew changed during this revision. Check it against the "
                "original before saving."
            )

    before_words = len(original.split())
    after_words = len(revised.split())
    if before_words >= 40:
        if after_words > before_words * 1.6:
            warnings.append(
                f"The revision grew from {before_words} to {after_words} words — "
                f"check nothing was invented."
            )
        elif after_words < before_words * 0.5:
            warnings.append(
                f"The revision shrank from {before_words} to {after_words} words — "
                f"check nothing important was lost."
            )

    return warnings


def _hebrew_runs(text: str) -> set[str]:
    import re

    return {
        run.strip()
        for run in re.findall(r"[֐-׿][֐-׿\s־'\"]*", text)
        if len(run.strip()) >= 4
    }
