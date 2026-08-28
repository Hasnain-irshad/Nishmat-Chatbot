"""
Lesson templates.

The lesson FORMAT and the WRITING STYLE live in these rows, not in code. That
is the whole point: the client can reshape her lesson structure, retitle a
section, or adjust the tone instructions without anyone touching Python.

Editing a template snapshots the previous version first, so a lesson generated
last month can still be explained by the template that actually produced it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.api.deps import AdminDep
from app.db import supabase
from app.logging import get_logger

log = get_logger("api.admin_templates")

router = APIRouter(prefix="/templates", tags=["admin:templates"])

TEMPLATE_COLUMNS = (
    "id, name, description, series_title, sections, optional_addons, "
    "style_guide, formatting_rules, constraints, signoff, is_default, "
    "version, created_at, updated_at"
)


class TemplateSection(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=120)
    required: bool = True
    dir: str = "ltr"
    order: int = 0
    guidance: str | None = Field(default=None, max_length=2000)
    max_words: int | None = Field(default=None, ge=1, le=5000)

    @field_validator("dir")
    @classmethod
    def _valid_dir(cls, value: str) -> str:
        if value not in ("ltr", "rtl"):
            raise ValueError("dir must be 'ltr' or 'rtl'")
        return value


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: str | None
    series_title: str | None
    sections: list[dict[str, Any]]
    optional_addons: list[dict[str, Any]]
    style_guide: str
    formatting_rules: dict[str, Any]
    constraints: dict[str, Any]
    signoff: str | None
    is_default: bool
    version: int
    created_at: str
    updated_at: str


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    series_title: str | None = Field(default=None, max_length=200)
    sections: list[TemplateSection] | None = None
    style_guide: str | None = Field(default=None, max_length=20_000)
    formatting_rules: dict[str, Any] | None = None
    constraints: dict[str, Any] | None = None
    signoff: str | None = Field(default=None, max_length=200)


@router.get("", response_model=list[TemplateResponse])
async def list_templates(user: AdminDep) -> list[TemplateResponse]:
    rows = await supabase.service().select(
        "lesson_templates", columns=TEMPLATE_COLUMNS, order="is_default.desc,name.asc"
    )
    return [TemplateResponse(**row) for row in rows]


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: str, user: AdminDep) -> TemplateResponse:
    row = await supabase.service().select(
        "lesson_templates",
        columns=TEMPLATE_COLUMNS,
        filters={"id": f"eq.{template_id}"},
        single=True,
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That template was not found.")
    return TemplateResponse(**row)


@router.patch("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: str, payload: TemplateUpdate, user: AdminDep
) -> TemplateResponse:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to update.")

    db = supabase.service()

    existing = await db.select(
        "lesson_templates",
        columns=TEMPLATE_COLUMNS,
        filters={"id": f"eq.{template_id}"},
        single=True,
    )
    if not existing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That template was not found.")

    if "sections" in changes:
        sections = changes["sections"]
        if not sections:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "A template needs at least one section."
            )
        keys = [section["key"] for section in sections]
        if len(keys) != len(set(keys)):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Section keys must be unique."
            )
        # Renumber so `order` always reflects the list the admin sees.
        for index, section in enumerate(sections, start=1):
            section["order"] = index

    # Snapshot the current state before overwriting it. Templates are edited
    # rarely and referenced by every lesson generated under them, so losing an
    # old one would make past output unexplainable.
    try:
        await db.insert(
            "lesson_template_versions",
            {
                "template_id": template_id,
                "version": existing["version"],
                "snapshot": existing,
                "created_by": user.id,
            },
            returning=False,
        )
    except supabase.SupabaseError:
        log.warning("template_snapshot_failed", template_id=template_id)

    changes["version"] = existing["version"] + 1

    rows = await db.update("lesson_templates", {"id": f"eq.{template_id}"}, changes)
    row = rows[0] if isinstance(rows, list) else rows

    log.info(
        "template_updated",
        template_id=template_id,
        version=changes["version"],
        fields=sorted(k for k in changes if k != "version"),
        by=user.id,
    )
    return TemplateResponse(**row)
