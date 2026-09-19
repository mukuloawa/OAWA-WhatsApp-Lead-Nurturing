from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from nurture.ghl.models import Contact, Message
from nurture.settings import Settings
from nurture.store.db import make_session_factory
from nurture.store.models import Base
from nurture.worker.engine_interface import ConversationEngine, EngineDecision

GHL_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ghl"


@pytest.fixture
def load_ghl_fixture():
    """Returns a callable: load_ghl_fixture("get_contact.json") -> dict.

    A fixture rather than a plain importable function, so tests don't
    depend on `tests/` being an importable package (that broke under a
    plain `pytest` invocation, which doesn't add the repo root to
    sys.path the way `python -m pytest` does).
    """

    def _load(name: str) -> dict:
        return json.loads((GHL_FIXTURES_DIR / name).read_text())

    return _load

VALID_SETTINGS_KWARGS = dict(
    anthropic_api_key="sk-ant-test-000",
    ghl_token="ghl-test-token",
    ghl_location_id="FlT9bndDcWIrmuveZWZa",
    webhook_secret="x" * 32,
    admin_secret="admin-test-secret",
    database_url="sqlite+aiosqlite:///:memory:",
    webinar_link="https://example.com/webinar",
    session_when="Saturday, 11:00 AM IST",
)


@pytest.fixture
def valid_settings_kwargs() -> dict:
    return dict(VALID_SETTINGS_KWARGS)


@pytest.fixture
def test_settings(valid_settings_kwargs) -> Settings:
    # _env_file=None: ignore any real .env on disk so tests are hermetic.
    return Settings(_env_file=None, **valid_settings_kwargs)


@pytest.fixture
async def db_session_factory():
    """A fresh in-memory SQLite DB (schema created directly from the
    models, not via Alembic — that's covered separately by the migration
    checks) with StaticPool so all connections share the same in-memory
    database for the life of the test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield make_session_factory(engine)
    await engine.dispose()


class StubEngine(ConversationEngine):
    """DESIGN.md Section 16: 'a stubbed Claude returning canned tool
    outputs'. Test infrastructure, not the real Phase 4 engine. Defined
    here (not in a `tests.integration` submodule) so it can be imported
    without relying on `tests/` being an importable package — see the
    `load_ghl_fixture` fixture above for why that matters."""

    def __init__(self, decision) -> None:
        self._decision = decision
        self.calls: list[dict] = []

    async def decide(
        self, *, contact: Contact, thread: list[Message], known_fields: dict[str, str]
    ) -> EngineDecision:
        self.calls.append({"contact": contact, "thread": thread, "known_fields": known_fields})
        if callable(self._decision):
            return self._decision(contact=contact, thread=thread, known_fields=known_fields)
        return self._decision


@pytest.fixture
def stub_engine_factory():
    return StubEngine
