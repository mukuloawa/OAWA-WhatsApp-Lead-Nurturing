"""DB access for inbound_events and turns (DESIGN.md Section 6.2, Section 8)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nurture.store.models import InboundEvent, Turn


async def insert_inbound_event(
    session: AsyncSession, *, contact_id: str, payload: dict
) -> InboundEvent:
    event = InboundEvent(contact_id=contact_id, payload=payload, status="pending")
    session.add(event)
    await session.flush()
    return event


async def get_event(session: AsyncSession, event_id: int) -> InboundEvent | None:
    return await session.get(InboundEvent, event_id)


async def has_newer_pending_event(
    session: AsyncSession, *, contact_id: str, received_at: datetime, exclude_id: int
) -> bool:
    stmt = select(InboundEvent.id).where(
        InboundEvent.contact_id == contact_id,
        InboundEvent.status == "pending",
        InboundEvent.received_at > received_at,
        InboundEvent.id != exclude_id,
    )
    result = await session.execute(stmt)
    return result.first() is not None


async def mark_event_status(
    session: AsyncSession,
    event: InboundEvent,
    *,
    status: str,
    reason: str | None = None,
    processed_at: datetime | None = None,
) -> None:
    event.status = status
    event.status_reason = reason
    if processed_at is not None:
        event.processed_at = processed_at
    await session.flush()


async def get_pending_events_older_than(
    session: AsyncSession, *, cutoff: datetime
) -> list[InboundEvent]:
    stmt = select(InboundEvent).where(
        InboundEvent.status == "pending",
        InboundEvent.received_at <= cutoff,
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_last_turn(session: AsyncSession, *, contact_id: str) -> Turn | None:
    stmt = (
        select(Turn)
        .where(Turn.contact_id == contact_id)
        .order_by(Turn.created_at.desc(), Turn.id.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def insert_turn(session: AsyncSession, **fields) -> Turn:
    turn = Turn(**fields)
    session.add(turn)
    await session.flush()
    return turn
