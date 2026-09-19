"""FastAPI app factory.

Wires up /health, /ready, /webhook/wa-reply, /admin/replay, the DB
engine/session factory, the GHL adapter, the (stubbed, until Phase 4)
conversation engine, and the debounce scheduler. Business logic itself
lives in worker/pipeline.py and guards/; this module only wires
dependencies together.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from nurture.api.admin import router as admin_router
from nurture.api.health import router as health_router
from nurture.api.webhook import router as webhook_router
from nurture.ghl.client import GHLClient
from nurture.ghl.real import RealGHLClient
from nurture.settings import Settings, get_settings
from nurture.store.db import make_engine, make_session_factory
from nurture.worker.engine_interface import AlwaysEscalateEngine, ConversationEngine
from nurture.worker.scheduler import Scheduler


def create_app(
    settings: Settings | None = None,
    *,
    ghl_client: GHLClient | None = None,
    engine: ConversationEngine | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.db_engine = make_engine(settings.database_url)
        app.state.session_factory = make_session_factory(app.state.db_engine)

        app.state.ghl_client = ghl_client or RealGHLClient(
            base_url=settings.ghl_base_url,
            api_version=settings.ghl_api_version,
            token=settings.ghl_token,
            location_id=settings.ghl_location_id,
        )
        # No real conversation engine exists yet (Phase 4). Wiring in a
        # safe default that always escalates rather than leaving this
        # unset, so the pipeline is fully exercisable end to end now,
        # with the worst case (if ever deployed before Phase 4) being
        # "hands every conversation to a human" rather than guessing.
        app.state.engine = engine or AlwaysEscalateEngine()

        app.state.scheduler = Scheduler(
            session_factory=app.state.session_factory,
            ghl=app.state.ghl_client,
            engine=app.state.engine,
            settings=settings,
        )
        await app.state.scheduler.recover_pending_events()

        try:
            yield
        finally:
            await app.state.db_engine.dispose()

    app = FastAPI(title="OAWA WhatsApp Lead Nurturing Service", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(webhook_router)
    app.include_router(admin_router)
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
