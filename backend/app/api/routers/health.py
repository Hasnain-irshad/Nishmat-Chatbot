"""Liveness and readiness."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.db import supabase

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness. Must stay dependency-free so it answers even when Supabase is down."""
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.environment,
        "llm_mode": settings.llm_mode,
        "openai_configured": bool(settings.openai_api_key),
    }


@router.get("/health/ready")
async def ready() -> dict:
    """Readiness — actually touches the database."""
    checks: dict[str, str] = {}

    try:
        await supabase.service().select("series", columns="id", limit=1)
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unreachable"

    ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}
