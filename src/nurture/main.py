"""FastAPI app factory.

Phase 1 scope only: settings loading (fail-fast on missing config),
/health, /ready, and DB engine wiring. The webhook, admin, worker,
GHL adapter, guards and conversation engine are built in later phases
(DESIGN.md Section 17) and are not wired in here yet.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from nurture.api.health import router as health_router
from nurture.settings import Settings, get_settings
from nurture.store.db import make_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.db_engine = make_engine(settings.database_url)
        try:
            yield
        finally:
            await app.state.db_engine.dispose()

    app = FastAPI(title="OAWA WhatsApp Lead Nurturing Service", lifespan=lifespan)
    app.include_router(health_router)
    return app


def __getattr__(name: str):
    # Lazily builds the module-level `app` (used by `uvicorn nurture.main:app`)
    # only when it is actually accessed, not merely when this module is
    # imported for `create_app` (e.g. from tests, which pass their own
    # Settings). This is what makes the fail-fast behaviour below real
    # fail-fast-on-startup rather than fail-fast-on-any-import.
    #
    # Fails fast when `app` is accessed if required config is missing, per
    # DESIGN.md Section 11 ("the app refuses to start if any required one
    # is missing").
    if name == "app":
        return create_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
