"""POST /webhook/wa-reply integration tests (DESIGN.md Section 7.1)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from nurture.ghl import Contact, FakeGHLClient, Message
from nurture.ghl.fields import WA_CUSTOM_FIELD_KEYS
from nurture.main import create_app
from nurture.settings import Settings
from nurture.store import repository
from nurture.store.models import Base


def make_field_ids() -> dict[str, str]:
    return {key: f"field-id-{key}" for key in WA_CUSTOM_FIELD_KEYS}


@pytest.fixture
async def app_settings(tmp_path, valid_settings_kwargs) -> Settings:
    """Unlike `test_settings` (in-memory, schema-less — fine for /ready's
    SELECT 1), the app under test here actually inserts rows, and the
    app creates its own DB engine independent of any test fixture engine.
    A real file-backed SQLite DB (with the schema pre-created, since the
    app itself never runs migrations — DESIGN.md Section 18: "Migrations
    run as a release step, not on app start") is needed so every
    connection the app opens sees the same tables."""
    db_path = tmp_path / "webhook_test.db"
    kwargs = dict(valid_settings_kwargs)
    kwargs["database_url"] = f"sqlite+aiosqlite:///{db_path}"
    settings = Settings(_env_file=None, **kwargs)

    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    return settings


def test_missing_secret_header_is_rejected(app_settings):
    app = create_app(settings=app_settings, ghl_client=FakeGHLClient())
    with TestClient(app) as client:
        resp = client.post("/webhook/wa-reply", json={"contact_id": "c1", "location_id": "loc"})
    assert resp.status_code == 401


def test_wrong_secret_is_rejected(app_settings):
    app = create_app(settings=app_settings, ghl_client=FakeGHLClient())
    with TestClient(app) as client:
        resp = client.post(
            "/webhook/wa-reply",
            json={"contact_id": "c1", "location_id": "loc"},
            headers={"X-OAWA-Secret": "wrong"},
        )
    assert resp.status_code == 401


def test_missing_contact_id_is_rejected(app_settings):
    app = create_app(settings=app_settings, ghl_client=FakeGHLClient())
    with TestClient(app) as client:
        resp = client.post(
            "/webhook/wa-reply",
            json={"location_id": app_settings.ghl_location_id},
            headers={"X-OAWA-Secret": app_settings.webhook_secret},
        )
    assert resp.status_code == 400


def test_wrong_location_id_is_rejected(app_settings):
    app = create_app(settings=app_settings, ghl_client=FakeGHLClient())
    with TestClient(app) as client:
        resp = client.post(
            "/webhook/wa-reply",
            json={"contact_id": "c1", "location_id": "some-other-location"},
            headers={"X-OAWA-Secret": app_settings.webhook_secret},
        )
    assert resp.status_code == 409


def test_valid_webhook_is_accepted_and_creates_event(app_settings):
    app_settings.debounce_seconds = 3600  # long enough that the test never actually fires it
    fake_ghl = FakeGHLClient()
    app = create_app(settings=app_settings, ghl_client=fake_ghl)
    with TestClient(app) as client:
        resp = client.post(
            "/webhook/wa-reply",
            json={
                "contact_id": "c1",
                "location_id": app_settings.ghl_location_id,
                "extra": "ignored",
            },
            headers={"X-OAWA-Secret": app_settings.webhook_secret},
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    assert "event_id" in body


async def test_valid_webhook_eventually_triggers_processing(app_settings):
    app_settings.debounce_seconds = 0
    inbound = Message(
        id="m1",
        direction="inbound",
        text="hi",
        sent_at=datetime.now(timezone.utc),
        sent_by_service=False,
    )
    contact = Contact(id="c1", first_name="Rahul", city="Pune", tags=set(), fields={})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [inbound]}, field_ids=make_field_ids()
    )
    app = create_app(settings=app_settings, ghl_client=fake_ghl)

    with TestClient(app) as client:
        resp = client.post(
            "/webhook/wa-reply",
            json={"contact_id": "c1", "location_id": app_settings.ghl_location_id},
            headers={"X-OAWA-Secret": app_settings.webhook_secret},
        )
        assert resp.status_code == 202
        event_id = resp.json()["event_id"]

        session_factory = app.state.session_factory
        event = None
        for _ in range(50):
            async with session_factory() as session:
                event = await repository.get_event(session, event_id)
                if event.status != "pending":
                    break
            await asyncio.sleep(0.02)

    assert event is not None
    assert event.status in ("processed", "skipped")  # AlwaysEscalateEngine still "processes" it
