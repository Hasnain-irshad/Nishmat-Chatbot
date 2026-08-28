"""
Job queue client.

Thin wrapper over the SQL functions in `0004_job_queue.sql`. Every operation
that must be atomic — claiming, failing with retry — happens inside Postgres,
so nothing here needs a lock of its own.

The interface is deliberately small. If this ever moves to a real broker, this
file is the only thing that changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db import supabase
from app.logging import get_logger

log = get_logger("jobs.queue")


class JobType:
    """Known job types. Strings, so a job row stays readable in SQL."""

    EXTRACT_FILE = "extract_file"
    GENERATE_LESSON = "generate_lesson"
    MODIFY_LESSON = "modify_lesson"
    INDEX_LESSON = "index_lesson"
    UNINDEX_LESSON = "unindex_lesson"
    SUMMARISE_CONVERSATION = "summarise_conversation"


@dataclass
class Job:
    id: str
    type: str
    payload: dict
    status: str
    attempts: int
    max_attempts: int
    lesson_id: str | None
    created_by: str | None

    @classmethod
    def from_row(cls, row: dict) -> "Job":
        return cls(
            id=row["id"],
            type=row["type"],
            payload=row.get("payload") or {},
            status=row["status"],
            attempts=row.get("attempts", 0),
            max_attempts=row.get("max_attempts", 3),
            lesson_id=row.get("lesson_id"),
            created_by=row.get("created_by"),
        )


async def enqueue(
    job_type: str,
    payload: dict,
    *,
    lesson_id: str | None = None,
    created_by: str | None = None,
    max_attempts: int = 3,
) -> str:
    """Queue a job and return its id. The caller polls `GET /jobs/{id}`."""
    row = await supabase.service().insert(
        "jobs",
        {
            "type": job_type,
            "payload": payload,
            "lesson_id": lesson_id,
            "created_by": created_by,
            "max_attempts": max_attempts,
            "status": "queued",
            "progress_stage": "queued",
        },
    )
    job_id = row[0]["id"] if isinstance(row, list) else row["id"]
    log.info("job_enqueued", job_id=job_id, type=job_type, lesson_id=lesson_id)
    return job_id


async def claim(worker: str, types: list[str] | None = None) -> Job | None:
    """Claim one queued job, or None if the queue is empty."""
    rows = await supabase.service().rpc(
        "claim_job", {"p_worker": worker, "p_types": types}
    )
    if not rows:
        return None
    row = rows[0] if isinstance(rows, list) else rows
    return Job.from_row(row)


async def complete(job_id: str, result: dict[str, Any] | None = None) -> None:
    await supabase.service().rpc(
        "complete_job", {"p_job_id": job_id, "p_result": result or {}}
    )
    log.info("job_completed", job_id=job_id)


async def fail(job_id: str, error: str, *, retry: bool = True) -> str:
    """Mark a job failed. Returns the resulting status: 'queued' or 'failed'."""
    status = await supabase.service().rpc(
        "fail_job", {"p_job_id": job_id, "p_error": error, "p_retry": retry}
    )
    log.warning("job_failed", job_id=job_id, outcome=status, error=error[:200])
    return status if isinstance(status, str) else "failed"


async def progress(job_id: str, stage: str, pct: int | None = None) -> None:
    """
    Report progress so the admin sees a real stage name rather than a spinner.
    Never allowed to break the job it is reporting on.
    """
    try:
        await supabase.service().rpc(
            "update_job_progress",
            {"p_job_id": job_id, "p_stage": stage, "p_pct": pct},
        )
    except Exception:
        log.warning("job_progress_failed", job_id=job_id, stage=stage)


async def reap_stale(timeout_seconds: int = 900) -> int:
    """Requeue jobs whose worker died. Returns how many were recovered."""
    count = await supabase.service().rpc(
        "reap_stale_jobs", {"p_timeout_seconds": timeout_seconds}
    )
    recovered = int(count or 0)
    if recovered:
        log.warning("stale_jobs_reaped", count=recovered)
    return recovered


async def get(job_id: str) -> dict | None:
    return await supabase.service().select(
        "jobs",
        columns="id, type, status, progress_stage, progress_pct, error, result, "
        "lesson_id, created_by, attempts, max_attempts, created_at, updated_at",
        filters={"id": f"eq.{job_id}"},
        single=True,
    )
