"""
Job status.

The frontend polls this while a file is processing or a lesson is generating,
so it can show a real stage name rather than an indefinite spinner.

Visibility rule: you can see your own jobs; an admin can see any. Job payloads
can name lessons that are not published, so this is not public.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.api.deps import CurrentUserDep
from app.jobs import queue

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobResponse(BaseModel):
    id: str
    type: str
    status: str
    progress_stage: str | None
    progress_pct: int
    error: str | None
    result: dict | None
    lesson_id: str | None
    attempts: int
    max_attempts: int
    created_at: str
    updated_at: str

    @property
    def is_finished(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled")


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, user: CurrentUserDep) -> JobResponse:
    row = await queue.get(job_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That job was not found.")

    if not user.is_admin and row.get("created_by") != user.id:
        # 404 rather than 403: do not confirm that someone else's job exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That job was not found.")

    row.pop("created_by", None)
    return JobResponse(**row)
