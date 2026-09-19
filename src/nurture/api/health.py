"""Liveness and readiness endpoints (DESIGN.md Section 7.1).

/health: liveness only, no dependencies.
/ready: DB reachable. GHL field-ID map resolution (the other half of
readiness per Section 7.1) is added in Phase 2 once the GHL adapter
exists — until then this endpoint only reports the checks it can
actually perform, rather than assuming GHL is fine.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict:
    from nurture.store.db import db_is_reachable

    engine = request.app.state.db_engine
    db_ok = await db_is_reachable(engine)

    checks = {
        "database": db_ok,
        "ghl_field_ids": None,  # not implemented until Phase 2 (GHL adapter)
    }
    ready_ = db_ok
    response.status_code = 200 if ready_ else 503
    return {"status": "ok" if ready_ else "not_ready", "checks": checks}
