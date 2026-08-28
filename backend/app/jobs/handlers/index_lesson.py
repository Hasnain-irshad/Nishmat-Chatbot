"""
Job handler: build or remove a lesson's chunks in the chatbot index.

Queued on publish. Unpublishing deletes the chunks synchronously instead —
a queued removal would leave a window where a withdrawn lesson is still
retrievable, and that window is exactly the thing the rule exists to prevent.
"""

from __future__ import annotations

from app.jobs import queue
from app.llm.types import BudgetExceeded
from app.logging import get_logger
from app.services import indexing_service

log = get_logger("jobs.index_lesson")


class Terminal(Exception):
    """A failure retrying cannot fix."""


async def run(job: queue.Job) -> dict:
    lesson_id = job.payload.get("lesson_id")
    if not lesson_id:
        raise ValueError("index_lesson job has no lesson_id")

    await queue.progress(job.id, "Building the search index", 40)

    try:
        result = await indexing_service.index_lesson(
            lesson_id, version_id=job.payload.get("version_id")
        )
    except indexing_service.IndexingError as exc:
        raise Terminal(str(exc)) from exc
    except BudgetExceeded as exc:
        raise Terminal(str(exc)) from exc

    await queue.progress(job.id, "Done", 100)
    return result


async def run_unindex(job: queue.Job) -> dict:
    lesson_id = job.payload.get("lesson_id")
    if not lesson_id:
        raise ValueError("unindex_lesson job has no lesson_id")
    return await indexing_service.unindex_lesson(lesson_id)
