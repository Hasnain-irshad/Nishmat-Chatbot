"""
Error handling.

Two rules:

  1. A person gets a sentence they can act on. Never a stack trace, never a
     database message, never anything naming our internals.
  2. Every failure carries a `request_id` that also appears in the logs, so a
     user can quote it and we can find the actual cause.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.db.supabase import SupabaseError
from app.logging import get_logger

log = get_logger("api.errors")

REQUEST_ID_HEADER = "X-Request-ID"


def _request_id(request: Request) -> str:
    existing = getattr(request.state, "request_id", None)
    if existing:
        return existing
    generated = uuid.uuid4().hex[:12]
    request.state.request_id = generated
    return generated


def _body(message: str, request_id: str, code: str | None = None) -> dict:
    payload = {"error": message, "request_id": request_id}
    if code:
        payload["code"] = code
    return payload


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        request_id = _request_id(request)
        # 4xx is the caller's problem and is already phrased for them.
        if exc.status_code >= 500:
            log.error("http_error", status=exc.status_code, detail=str(exc.detail),
                      path=request.url.path, request_id=request_id)
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(str(exc.detail), request_id),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        request_id = _request_id(request)
        # Surface which field was wrong, but not the internal model shape.
        fields = []
        for error in exc.errors():
            location = [str(p) for p in error.get("loc", []) if p not in ("body", "query")]
            if location:
                fields.append(".".join(location))
        detail = (
            f"Invalid value for: {', '.join(fields)}."
            if fields
            else "The request was not valid."
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_body(detail, request_id, "validation_error"),
        )

    @app.exception_handler(SupabaseError)
    async def supabase_error(request: Request, exc: SupabaseError):
        request_id = _request_id(request)
        log.error("database_error", status=exc.status, code=exc.code,
                  detail=str(exc), path=request.url.path, request_id=request_id)

        # PostgREST's own message can name columns and constraints — do not
        # forward it. Map to something safe.
        if exc.status == 503:
            message = "The database is unreachable right now. Please try again."
            code = "database_unavailable"
        elif exc.status in (401, 403):
            message = "You do not have access to that."
            code = "forbidden"
        elif exc.code == "23505":
            message = "That already exists."
            code = "duplicate"
        else:
            message = "Something went wrong saving your work. Please try again."
            code = "database_error"

        http_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if exc.status == 503
            else status.HTTP_403_FORBIDDEN
            if exc.status in (401, 403)
            else status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(status_code=http_status, content=_body(message, request_id, code))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        request_id = _request_id(request)
        log.exception("unhandled_error", path=request.url.path, request_id=request_id)

        settings = get_settings()
        message = (
            "Something went wrong. Please try again."
            if settings.is_production
            # In development the exact error is far more useful than a
            # reassuring sentence — but it never leaks in production.
            else f"{type(exc).__name__}: {exc}"
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body(message, request_id, "internal_error"),
        )
