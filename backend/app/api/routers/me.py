"""The signed-in person's own profile."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUserDep

router = APIRouter(tags=["me"])


class MeResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    is_admin: bool


@router.get("/me", response_model=MeResponse)
async def read_me(user: CurrentUserDep) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_admin=user.is_admin,
    )
