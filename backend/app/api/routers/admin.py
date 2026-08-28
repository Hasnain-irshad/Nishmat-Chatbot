"""
Admin router.

`require_admin` is attached to the router itself, so every route mounted here
inherits the check. A new admin endpoint cannot be added without it — which is
the point. `tests/test_security.py` asserts this holds for every route.

Feature endpoints land here as their phases are built.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import AdminDep, require_admin
from app.api.routers import admin_lessons, admin_references, admin_templates, files
from app.db import supabase

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)

# Mounted here so it inherits require_admin. Never mount it on the app
# directly — that would bypass the router-level check.
router.include_router(files.router)
router.include_router(admin_lessons.router)
router.include_router(admin_templates.router)
router.include_router(admin_references.router)


class AdminOverview(BaseModel):
    lessons_total: int
    lessons_published: int
    lessons_needing_review: int
    style_examples: int
    ai_spend_usd: float
    ai_spend_cap_usd: float


@router.get("/overview", response_model=AdminOverview)
async def overview(user: AdminDep) -> AdminOverview:
    from app.config import get_settings

    db = supabase.service()

    lessons = await db.select("lessons", columns="status, needs_review, deleted_at")
    live = [l for l in lessons if l.get("deleted_at") is None]

    styles = await db.select("style_examples", columns="id")
    usage = await db.select("ai_usage", columns="estimated_cost")
    spend = sum(float(row.get("estimated_cost") or 0) for row in usage)

    return AdminOverview(
        lessons_total=len(live),
        lessons_published=sum(1 for l in live if l.get("status") == "published"),
        lessons_needing_review=sum(1 for l in live if l.get("needs_review")),
        style_examples=len(styles),
        ai_spend_usd=round(spend, 4),
        ai_spend_cap_usd=get_settings().ai_spend_cap_usd,
    )
