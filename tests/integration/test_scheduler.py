"""Debounce and startup-recovery tests (DESIGN.md Section 8, step 3)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from nurture.ghl import Contact, FakeGHLClient, Message
from nurture.ghl.fields import WA_CUSTOM_FIELD_KEYS
from nurture.settings import Settings
from nurture.store import repository
from nurture.worker.engine_interface import EngineDecision
from nurture.worker.scheduler import Scheduler


def make_field_ids() -> dict[str, str]:
    return {key: f"field-id-{key}" for key in WA_CUSTOM_FIELD_KEYS}


def settings_with(valid_settings_kwargs, **overrides) -> Settings:
    kwargs = dict(valid_settings_kwargs)
    kwargs.update(overrides)
    return Settings(_env_file=None, **kwargs)


async def test_schedule_waits_for_debounce_before_processing(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    inbound = Message(
        id="m1", direction="inbound", text="hi", sent_at=datetime.now(timezone.utc), sent_by_service=False
    )
    contact = Contact(id="c1", first_name="Rahul", city="Pune", tags=set(), fields={})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [inbound]}, field_ids=make_field_ids()
    )
    engine = stub_engine_factory(
        EngineDecision(reply="hi", stage="basics", extracted={}, escalate=False)
    )
    settings = settings_with(valid_settings_kwargs, send_mode="dry_run", debounce_seconds=1)
    settings.debounce_seconds = 0.1  # bypasses int-only validation; only enforced on construction
    scheduler = Scheduler(
        session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    async with db_session_factory() as session:
        async with session.begin():
            event = await repository.insert_inbound_event(
                session, contact_id="c1", payload={"contact_id": "c1"}
            )
        event_id = event.id

    task = scheduler.schedule(event_id)

    # Immediately after scheduling, nothing should have happened yet.
    await asyncio.sleep(0.02)
    assert fake_ghl.calls == []

    await task  # wait for the debounce + processing to finish

    assert fake_ghl.calls != []
    async with db_session_factory() as session:
        processed_event = await repository.get_event(session, event_id)
        assert processed_event.status == "processed"


async def test_recover_pending_events_picks_up_stale_events(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    inbound = Message(
        id="m1", direction="inbound", text="hi", sent_at=datetime.now(timezone.utc), sent_by_service=False
    )
    contact = Contact(id="c1", first_name="Rahul", city="Pune", tags=set(), fields={})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [inbound]}, field_ids=make_field_ids()
    )
    engine = stub_engine_factory(
        EngineDecision(reply="hi", stage="basics", extracted={}, escalate=False)
    )
    settings = settings_with(valid_settings_kwargs, send_mode="dry_run", debounce_seconds=20)
    scheduler = Scheduler(
        session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    old_received_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    async with db_session_factory() as session:
        async with session.begin():
            event = await repository.insert_inbound_event(
                session, contact_id="c1", payload={"contact_id": "c1"}
            )
            event.received_at = old_received_at
        event_id = event.id

    recovered_ids = await scheduler.recover_pending_events()
    assert recovered_ids == [event_id]

    # recover_pending_events fires off background tasks; give them a beat.
    for _ in range(20):
        async with db_session_factory() as session:
            processed_event = await repository.get_event(session, event_id)
            if processed_event.status == "processed":
                break
        await asyncio.sleep(0.01)

    assert processed_event.status == "processed"


async def test_recover_pending_events_ignores_recent_events(
    db_session_factory, valid_settings_kwargs, stub_engine_factory
):
    contact = Contact(id="c1", first_name="Rahul", city="Pune", tags=set(), fields={})
    fake_ghl = FakeGHLClient(contacts={"c1": contact}, threads={"c1": []}, field_ids=make_field_ids())
    engine = stub_engine_factory(
        EngineDecision(reply="hi", stage="basics", extracted={}, escalate=False)
    )
    settings = settings_with(valid_settings_kwargs, send_mode="dry_run", debounce_seconds=20)
    scheduler = Scheduler(
        session_factory=db_session_factory, ghl=fake_ghl, engine=engine, settings=settings
    )

    async with db_session_factory() as session:
        async with session.begin():
            await repository.insert_inbound_event(
                session, contact_id="c1", payload={"contact_id": "c1"}
            )
            # received_at defaults to "now" - well within the debounce window

    recovered_ids = await scheduler.recover_pending_events()
    assert recovered_ids == []
