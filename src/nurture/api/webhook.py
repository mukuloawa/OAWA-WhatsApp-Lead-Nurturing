"""POST /webhook/wa-reply (DESIGN.md Section 7.1)."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Request, Response

from nurture.store import repository

router = APIRouter()


@router.post("/webhook/wa-reply", status_code=202)
async def wa_reply(
    request: Request,
    response: Response,
    x_oawa_secret: str | None = Header(default=None),
) -> dict:
    settings = request.app.state.settings

    if x_oawa_secret is None or not hmac.compare_digest(x_oawa_secret, settings.webhook_secret):
        raise HTTPException(status_code=401, detail="invalid secret")

    body = await request.json()
    contact_id = body.get("contact_id")
    if not contact_id:
        raise HTTPException(status_code=400, detail="missing contact_id")

    location_id = body.get("location_id")
    if location_id != settings.ghl_location_id:
        raise HTTPException(status_code=409, detail="location_id mismatch")

    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        async with session.begin():
            event = await repository.insert_inbound_event(
                session, contact_id=contact_id, payload=body
            )
        event_id = event.id

    request.app.state.scheduler.schedule(event_id)
    return {"status": "accepted", "event_id": event_id}
