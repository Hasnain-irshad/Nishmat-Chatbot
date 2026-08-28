"""
Publishing.

This is where Rules 4, 5 and 6 are actually enforced:

  * only an explicitly published version is visible to a learner;
  * the chatbot's index is written on publish and deleted on unpublish, so
    learner visibility and retrieval visibility are the *same switch* and
    cannot drift apart;
  * publishing never mutates a version — it only moves a pointer, so history
    survives intact.

Nothing here is reachable without `require_admin`, and no model call can
trigger it. Publishing is always a human decision.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.db import supabase
from app.jobs import queue
from app.logging import get_logger

log = get_logger("services.publishing")


class PublishError(Exception):
    """Publishing was refused. The message is safe to show the admin."""


async def publish(lesson_id: str, version_id: str, *, actor_id: str) -> dict:
    db = supabase.service()

    lesson = await db.select(
        "lessons",
        columns="id, title, status, published_version_id, deleted_at",
        filters={"id": f"eq.{lesson_id}"},
        single=True,
    )
    if not lesson or lesson.get("deleted_at"):
        raise PublishError("That lesson no longer exists.")

    version = await db.select(
        "lesson_versions",
        columns="id, lesson_id, version_number, content, word_count",
        filters={"id": f"eq.{version_id}"},
        single=True,
    )
    if not version:
        raise PublishError("That version no longer exists.")

    # Guard against publishing a version of a *different* lesson — a copy-paste
    # of the wrong id would otherwise silently expose unrelated content.
    if version["lesson_id"] != lesson_id:
        raise PublishError("That version belongs to a different lesson.")

    sections = (version.get("content") or {}).get("sections") or []
    if not sections:
        raise PublishError(
            "This version has no content yet, so there is nothing to publish."
        )

    previous = lesson.get("published_version_id")

    updated = await db.update(
        "lessons",
        {"id": f"eq.{lesson_id}"},
        {
            "published_version_id": version_id,
            "current_version_id": version_id,
            "status": "published",
            "published_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    await _audit(
        actor_id,
        "lesson.published",
        lesson_id,
        {
            "version_id": version_id,
            "version_number": version["version_number"],
            "previous_version_id": previous,
        },
    )

    # Reindex so the chatbot answers from this version and no other.
    await queue.enqueue(
        queue.JobType.INDEX_LESSON,
        {"lesson_id": lesson_id, "version_id": version_id},
        lesson_id=lesson_id,
        created_by=actor_id,
    )

    log.info(
        "lesson_published",
        lesson_id=lesson_id,
        version=version["version_number"],
        by=actor_id,
    )
    return updated[0] if isinstance(updated, list) else updated


async def unpublish(lesson_id: str, *, actor_id: str) -> dict:
    """
    Withdraw a lesson.

    Clears the published pointer AND removes it from the chatbot index in the
    same action. If those were separate steps, a withdrawn lesson could keep
    being quoted back to learners.
    """
    db = supabase.service()

    lesson = await db.select(
        "lessons",
        columns="id, published_version_id, deleted_at",
        filters={"id": f"eq.{lesson_id}"},
        single=True,
    )
    if not lesson or lesson.get("deleted_at"):
        raise PublishError("That lesson no longer exists.")
    if not lesson.get("published_version_id"):
        raise PublishError("That lesson is not published.")

    updated = await db.update(
        "lessons",
        {"id": f"eq.{lesson_id}"},
        {"published_version_id": None, "status": "archived", "published_at": None},
    )

    # Delete the index synchronously — a queued removal would leave a window
    # in which a withdrawn lesson is still retrievable.
    await db.delete("lesson_chunks", {"lesson_id": f"eq.{lesson_id}"})

    await _audit(actor_id, "lesson.unpublished", lesson_id, {})
    log.info("lesson_unpublished", lesson_id=lesson_id, by=actor_id)

    return updated[0] if isinstance(updated, list) else updated


async def _audit(actor_id: str, action: str, entity_id: str, detail: dict) -> None:
    """Record a privileged action. Never allowed to fail the action itself."""
    try:
        await supabase.service().insert(
            "audit_log",
            {
                "actor_id": actor_id,
                "action": action,
                "entity_type": "lesson",
                "entity_id": entity_id,
                "detail": detail,
            },
            returning=False,
        )
    except Exception:
        log.exception("audit_write_failed", action=action, entity_id=entity_id)
