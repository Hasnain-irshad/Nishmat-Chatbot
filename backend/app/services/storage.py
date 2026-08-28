"""
Supabase Storage.

The bucket is private. Nothing here ever returns a public URL — the admin UI
gets a short-lived signed URL, and the worker downloads through the service
role. Source material is the client's unpublished work; a guessable public
link would leak it.

Storage keys are generated UUID paths, never the uploaded filename. That
removes path traversal, collisions, and the awkward question of what to do
with a Hebrew filename, all at once.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.logging import get_logger

log = get_logger("services.storage")


class StorageError(Exception):
    """A storage operation failed."""


@dataclass(frozen=True)
class StoredFile:
    path: str
    size_bytes: int


def build_key(kind: str, original_filename: str) -> str:
    """
    A stable, opaque storage key.

    Grouped by kind so the bucket stays browsable, and suffixed with the real
    extension so tooling that cares about it still works.
    """
    _, _, extension = original_filename.rpartition(".")
    suffix = f".{extension.lower()}" if extension and extension != original_filename else ""
    suffix = "".join(c for c in suffix if c.isalnum() or c == ".")[:12]
    return f"{kind}/{uuid.uuid4().hex}{suffix}"


def _headers(content_type: str | None = None) -> dict[str, str]:
    settings = get_settings()
    key = settings.supabase_service_role_key
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


async def upload(path: str, content: bytes, content_type: str) -> StoredFile:
    settings = get_settings()
    url = f"{settings.supabase_url}/storage/v1/object/{settings.supabase_storage_bucket}/{path}"

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            response = await client.post(
                url,
                content=content,
                headers={**_headers(content_type), "x-upsert": "false"},
            )
        except httpx.HTTPError as exc:
            raise StorageError(f"Could not reach storage: {exc}") from exc

    if response.status_code >= 400:
        raise StorageError(f"Upload failed ({response.status_code}): {response.text[:200]}")

    log.info("file_uploaded", path=path, bytes=len(content))
    return StoredFile(path=path, size_bytes=len(content))


async def download(path: str) -> bytes:
    settings = get_settings()
    url = f"{settings.supabase_url}/storage/v1/object/{settings.supabase_storage_bucket}/{path}"

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            response = await client.get(url, headers=_headers())
        except httpx.HTTPError as exc:
            raise StorageError(f"Could not reach storage: {exc}") from exc

    if response.status_code >= 400:
        raise StorageError(f"Download failed ({response.status_code})")
    return response.content


async def signed_url(path: str, expires_in: int = 900) -> str:
    """
    A time-limited URL for the admin UI. Fifteen minutes by default — long
    enough to open a document, short enough that a copied link goes stale.
    """
    settings = get_settings()
    url = (
        f"{settings.supabase_url}/storage/v1/object/sign/"
        f"{settings.supabase_storage_bucket}/{path}"
    )

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            url, json={"expiresIn": expires_in}, headers=_headers("application/json")
        )

    if response.status_code >= 400:
        raise StorageError(f"Could not sign that file ({response.status_code})")

    signed = response.json().get("signedURL") or response.json().get("signedUrl")
    if not signed:
        raise StorageError("Storage returned no signed URL")
    return f"{settings.supabase_url}/storage/v1{signed}"


async def delete(path: str) -> None:
    settings = get_settings()
    url = f"{settings.supabase_url}/storage/v1/object/{settings.supabase_storage_bucket}/{path}"

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.delete(url, headers=_headers())

    if response.status_code >= 400 and response.status_code != 404:
        raise StorageError(f"Delete failed ({response.status_code})")
    log.info("file_deleted", path=path)
