"""POST /admin/replay (DESIGN.md Section 7.1).

Runs the pipeline in dry_run regardless of the configured SEND_MODE, and
returns the would-be reply and extraction. Does not touch inbound_events
or turns — this is a read-and-decide preview only, not a real event.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from nurture.worker.pipeline import run_decision

router = APIRouter()


class ReplayBody(BaseModel):
    contact_id: str


@router.post("/admin/replay")
async def admin_replay(
    body: ReplayBody,
    request: Request,
    x_oawa_admin: str | None = Header(default=None),
) -> dict:
    settings = request.app.state.settings

    if x_oawa_admin is None or not hmac.compare_digest(x_oawa_admin, settings.admin_secret):
        raise HTTPException(status_code=401, detail="invalid admin secret")

    session_factory = request.app.state.session_factory
    ghl = request.app.state.ghl_client
    engine = request.app.state.engine

    async with session_factory() as session:
        async with session.begin():
            outcome = await run_decision(
                contact_id=body.contact_id,
                ghl=ghl,
                engine=engine,
                settings=settings,
                session=session,
                send_mode_override="dry_run",
            )

    return {
        "status": outcome.status,
        "reason": outcome.reason,
        "stage_before": outcome.stage_before,
        "stage_after": outcome.stage_after,
        "reply": outcome.reply_text,
        "extracted": outcome.extracted,
    }
