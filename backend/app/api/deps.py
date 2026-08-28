"""
Request dependencies — authentication and authorisation.

The critical rule of this file: **role comes from the database, never from the
token.** A JWT proves identity. It does not confer authority. If we read a role
claim out of the token, anyone who can influence their own user metadata could
grant themselves admin, and every product rule about who may publish a lesson
would rest on that claim being honest.

`require_admin` is mounted on the admin *router*, not on individual endpoints,
so a new admin route cannot accidentally ship without the check. There is a
test that asserts exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Header, HTTPException, status

from app.core.jwt import TokenError, verify_token
from app.db import supabase
from app.logging import get_logger


log = get_logger("api.deps")


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    full_name: str | None
    role: Literal["admin", "user"]
    access_token: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def db(self) -> supabase.SupabaseClient:
        """A database client scoped to this person, so RLS still applies."""
        return supabase.as_user(self.access_token)


def _bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not signed in.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    token = _bearer(authorization)

    try:
        claims = verify_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    # Read the profile with the service role: the caller is authenticated, and
    # we need the row to exist even before any RLS-visible state is set up.
    try:
        profile = await supabase.service().select(
            "profiles",
            columns="id, email, full_name, role",
            filters={"id": f"eq.{claims.subject}"},
            single=True,
        )
    except supabase.SupabaseError as exc:
        # Log the real cause. The caller gets a safe sentence, but swallowing
        # the detail entirely makes this failure undiagnosable in production.
        log.error(
            "profile_lookup_failed",
            status=exc.status,
            code=exc.code,
            detail=str(exc),
            user_id=claims.subject,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify your account. Please try again.",
        ) from exc

    if not profile:
        # Authenticated in Supabase but no profile row — the signup trigger
        # did not fire. Better to fail clearly than to invent a default role.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not fully set up. Please contact support.",
        )

    role = profile.get("role")
    if role not in ("admin", "user"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has no valid role.",
        )

    return CurrentUser(
        id=profile["id"],
        email=profile.get("email") or claims.email or "",
        full_name=profile.get("full_name"),
        role=role,
        access_token=token,
    )


async def require_admin(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
AdminDep = Annotated[CurrentUser, Depends(require_admin)]
