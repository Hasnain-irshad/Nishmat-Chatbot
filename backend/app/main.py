"""
Nishmat AI backend.

A modular monolith: one deployable, clear internal boundaries. Route handlers
stay thin — validate, call a service, shape a response. Business logic lives
in `app/services/`.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import REQUEST_ID_HEADER, register_error_handlers
from app.api.routers import admin, chat, health, jobs, me
from app.config import get_settings
from app.core.jwt import warm_jwks
from app.logging import configure_logging, get_logger

log = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()

    log.info(
        "starting",
        environment=settings.environment,
        llm_mode=settings.llm_mode,
        openai_configured=bool(settings.openai_api_key),
    )
    if settings.llm_mode == "mock":
        log.info("llm_mock_mode", detail="AI calls replay fixtures; nothing is billed")

    # Pull the signing keys now so the first authenticated request is not slow.
    await warm_jwks()

    yield
    log.info("stopping")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Nishmat AI",
        description="Backend for the Nishmat lesson platform.",
        version="0.1.0",
        lifespan=lifespan,
        # No interactive docs in production — they map the whole attack surface.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
        request.state.request_id = request_id

        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        response.headers[REQUEST_ID_HEADER] = request_id

        # Health checks would otherwise dominate the log.
        if not request.url.path.startswith("/health"):
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                ms=elapsed_ms,
                request_id=request_id,
            )
        return response

    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(jobs.router)
    app.include_router(chat.router)
    app.include_router(admin.router)

    return app


app = create_app()
