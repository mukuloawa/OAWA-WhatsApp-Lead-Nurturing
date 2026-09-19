"""POST /admin/replay integration tests (DESIGN.md Section 7.1)."""

from __future__ import annotations

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
from nurture.worker.engine_interface import EngineDecision


def make_field_ids() -> dict[str, str]:
    return {key: f"field-id-{key}" for key in WA_CUSTOM_FIELD_KEYS}


@pytest.fixture
async def app_settings(tmp_path, valid_settings_kwargs) -> Settings:
    db_path = tmp_path / "admin_test.db"
    kwargs = dict(valid_settings_kwargs)
    kwargs["database_url"] = f"sqlite+aiosqlite:///{db_path}"
    settings = Settings(_env_file=None, **kwargs)

    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    return settings


class _FixedEngine:
    def __init__(self, decision: EngineDecision) -> None:
        self._decision = decision

    async def decide(self, *, contact, thread, known_fields):
        return self._decision


def test_wrong_admin_secret_is_rejected(app_settings):
    app = create_app(settings=app_settings, ghl_client=FakeGHLClient())
    with TestClient(app) as client:
        resp = client.post(
            "/admin/replay", json={"contact_id": "c1"}, headers={"X-OAWA-Admin": "wrong"}
        )
    assert resp.status_code == 401


def test_missing_admin_header_is_rejected(app_settings):
    app = create_app(settings=app_settings, ghl_client=FakeGHLClient())
    with TestClient(app) as client:
        resp = client.post("/admin/replay", json={"contact_id": "c1"})
    assert resp.status_code == 401


def test_replay_forces_dry_run_regardless_of_configured_mode(app_settings, tmp_path):
    app_settings.send_mode = "live"  # configured mode is live...
    # ...which requires a real (non-"FILL IN") agenda to even start
    # (DESIGN.md Section 11); the shared real config/agenda.yaml
    # deliberately still has the placeholder (OAWA hasn't supplied the
    # real one yet), so this test supplies its own.
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "agenda.yaml").write_text("agenda:\n  - Test agenda item\n")
    (config_dir / "optout.yaml").write_text("patterns: []\n")
    (config_dir / "banned_phrases.yaml").write_text("phrases: []\n")
    app_settings.config_dir = config_dir
    inbound = Message(
        id="m1", direction="inbound", text="6 crore", sent_at=datetime.now(timezone.utc), sent_by_service=False
    )
    contact = Contact(id="c1", first_name="Rahul", city="Pune", tags={"wa-stage-1"}, fields={})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [inbound]}, field_ids=make_field_ids()
    )
    decision = EngineDecision(
        reply="Got it, years in business?", stage="basics", extracted={"aum": "6 crore"}, escalate=False
    )
    app = create_app(settings=app_settings, ghl_client=fake_ghl, engine=_FixedEngine(decision))

    with TestClient(app) as client:
        resp = client.post(
            "/admin/replay",
            json={"contact_id": "c1"},
            headers={"X-OAWA-Admin": app_settings.admin_secret},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "processed"
    assert body["reply"] == decision.reply
    assert body["stage_after"] == "basics"
    assert body["extracted"] == {"aum": "6 crore"}

    # ...but nothing was actually written to GHL, because /admin/replay
    # always forces dry_run (DESIGN.md Section 7.1).
    called_methods = [c.method for c in fake_ghl.calls]
    assert "send_whatsapp" not in called_methods
    assert "update_custom_fields" not in called_methods
    assert "set_tags" not in called_methods
    assert contact.tags == {"wa-stage-1"}
    assert contact.fields == {}


async def test_replay_does_not_touch_inbound_events_or_turns(app_settings):
    inbound = Message(
        id="m1", direction="inbound", text="6 crore", sent_at=datetime.now(timezone.utc), sent_by_service=False
    )
    contact = Contact(id="c1", first_name="Rahul", city="Pune", tags={"wa-stage-1"}, fields={})
    fake_ghl = FakeGHLClient(
        contacts={"c1": contact}, threads={"c1": [inbound]}, field_ids=make_field_ids()
    )
    decision = EngineDecision(reply="hi", stage="basics", extracted={}, escalate=False)
    app = create_app(settings=app_settings, ghl_client=fake_ghl, engine=_FixedEngine(decision))

    with TestClient(app) as client:
        resp = client.post(
            "/admin/replay",
            json={"contact_id": "c1"},
            headers={"X-OAWA-Admin": app_settings.admin_secret},
        )
        assert resp.status_code == 200

        session_factory = app.state.session_factory

    async with session_factory() as session:
        turn = await repository.get_last_turn(session, contact_id="c1")
        assert turn is None
