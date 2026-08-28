"""
Thin async PostgREST client.

Two modes, and the distinction matters:

  * `service()` uses the service-role key and **bypasses RLS**. Reserved for
    genuinely privileged work — publishing, indexing, background jobs.
  * `as_user(token)` forwards the caller's own access token, so every policy
    in the database still applies. This is the default for anything acting on
    behalf of a person.

Defaulting to the service role "because it always works" would quietly delete
our second line of defence, so it is never the default here.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx

from app.config import get_settings


class SupabaseError(Exception):
    """A PostgREST call failed."""

    def __init__(self, status: int, message: str, code: str | None = None):
        self.status = status
        self.code = code
        super().__init__(message)


class SupabaseClient:
    def __init__(self, token: str, *, is_service_role: bool = False):
        settings = get_settings()
        self._base = settings.supabase_url
        self._anon = settings.supabase_anon_key
        self._token = token
        self.is_service_role = is_service_role

    # ------------------------------------------------------------------ #

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        # PostgREST resolves the caller's Postgres role from `apikey`, and only
        # parses `Authorization` as a JWT.
        #
        # For a user request the two differ deliberately: the project's
        # publishable key identifies the project, the user's JWT identifies the
        # person, and RLS applies.
        #
        # For the service role they must be the SAME key. Newer Supabase secret
        # keys (`sb_secret_...`) are opaque, not JWTs — putting one in
        # `Authorization` alongside an anon `apikey` makes PostgREST try to
        # parse it as a token and fail with "Expected 3 parts in JWT".
        api_key = self._token if self.is_service_role else self._anon

        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    async def _request(
        self,
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        prefer: str | None = None,
    ) -> Any:
        settings = get_settings()
        extra = {"Prefer": prefer} if prefer else None

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.request(
                    method,
                    f"{self._base}{path}",
                    params=params,
                    json=json,
                    headers=self._headers(extra),
                )
            except httpx.HTTPError as exc:
                raise SupabaseError(503, f"Database unreachable: {exc}") from exc

        if response.status_code >= 400:
            detail, code = _parse_error(response)
            raise SupabaseError(response.status_code, detail, code)

        if not response.content:
            return None
        return response.json()

    # ---- PostgREST verbs ---------------------------------------------- #

    async def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: dict[str, str] | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        single: bool = False,
    ) -> Any:
        params: dict[str, Any] = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

        prefer = "count=exact" if limit is not None else None
        rows = await self._request("GET", f"/rest/v1/{table}", params=params, prefer=prefer)

        if single:
            if isinstance(rows, list):
                return rows[0] if rows else None
            return rows
        return rows or []

    async def insert(self, table: str, values: Any, *, returning: bool = True) -> Any:
        prefer = "return=representation" if returning else "return=minimal"
        return await self._request("POST", f"/rest/v1/{table}", json=values, prefer=prefer)

    async def update(
        self, table: str, filters: dict[str, str], values: dict, *, returning: bool = True
    ) -> Any:
        prefer = "return=representation" if returning else "return=minimal"
        return await self._request(
            "PATCH", f"/rest/v1/{table}", params=filters, json=values, prefer=prefer
        )

    async def delete(self, table: str, filters: dict[str, str]) -> Any:
        return await self._request("DELETE", f"/rest/v1/{table}", params=filters)

    async def rpc(self, function: str, params: dict) -> Any:
        return await self._request("POST", f"/rest/v1/rpc/{function}", json=params)


def _parse_error(response: httpx.Response) -> tuple[str, str | None]:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200], None
    if isinstance(body, dict):
        return (
            body.get("message") or body.get("hint") or "Database error",
            body.get("code"),
        )
    return str(body)[:200], None


# ---------------------------------------------------------------------- #


def service() -> SupabaseClient:
    """Privileged client. Bypasses RLS — use only where that is intended."""
    settings = get_settings()
    return SupabaseClient(settings.supabase_service_role_key, is_service_role=True)


def as_user(access_token: str) -> SupabaseClient:
    """Client acting as the signed-in person. RLS applies."""
    return SupabaseClient(access_token)
