from __future__ import annotations

from fastapi.testclient import TestClient

from nurture.main import create_app


def test_health_returns_ok(test_settings):
    app = create_app(settings=test_settings)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_returns_200_when_db_reachable(test_settings):
    app = create_app(settings=test_settings)
    with TestClient(app) as client:
        resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] is True


def test_ready_returns_503_when_db_unreachable(valid_settings_kwargs):
    from nurture.settings import Settings

    bad = dict(valid_settings_kwargs)
    # Port 1 on localhost: nothing listens there, so the connection fails fast.
    bad["database_url"] = "postgresql+asyncpg://nouser:nopass@127.0.0.1:1/nonexistent"
    settings = Settings(_env_file=None, **bad)

    app = create_app(settings=settings)
    with TestClient(app) as client:
        resp = client.get("/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] is False
