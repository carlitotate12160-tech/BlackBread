from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from blackbread.app import create_app
from blackbread.config import Settings
from blackbread.health import Readiness


def settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://user:password@localhost/test",
        artifact_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
    )


def test_liveness() -> None:
    app = create_app(settings())

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive", "version": "0.1.0"}


def test_readiness_succeeds_when_database_is_migrated() -> None:
    app = create_app(settings())
    readiness = Readiness(ready=True, database="available", migrations="0001_m0_bootstrap")

    with (
        patch("blackbread.app.check_readiness", AsyncMock(return_value=readiness)),
        TestClient(app) as client,
    ):
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "available",
        "migrations": "0001_m0_bootstrap",
    }


def test_readiness_fails_closed_when_database_is_unavailable() -> None:
    app = create_app(settings())
    readiness = Readiness(ready=False, database="unavailable", migrations="unknown")

    with (
        patch("blackbread.app.check_readiness", AsyncMock(return_value=readiness)),
        TestClient(app) as client,
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
