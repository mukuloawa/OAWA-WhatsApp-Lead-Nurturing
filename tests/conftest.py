from __future__ import annotations

import pytest

from nurture.settings import Settings

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
