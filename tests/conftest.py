from __future__ import annotations

import json
from pathlib import Path

import pytest

from nurture.settings import Settings

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
