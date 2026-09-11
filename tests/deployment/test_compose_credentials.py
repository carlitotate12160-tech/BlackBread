"""Canonical Compose proofs for the database credential bootstrap.

Proof map:
  A/B  Compose validation fails closed on a missing or empty credential, and a
       fully supplied environment validates without rendering any credential.
  H    the Compose environment carries database components separately and never
       interpolates a raw password into a rendered SQLAlchemy URL string.

All credentials are synthetic per-run values; no real or repository-known secret
is used, printed, or asserted.
"""

from __future__ import annotations

import pytest
import yaml

from tests.deployment.credential_support import (
    COMPOSE,
    compose_config,
    compose_env,
)

pytestmark = pytest.mark.timeout(60)


@pytest.mark.parametrize(
    ("override", "expected_variable"),
    [
        ({"POSTGRES_MIGRATION_PASSWORD": None}, "POSTGRES_MIGRATION_PASSWORD"),
        ({"POSTGRES_MIGRATION_PASSWORD": ""}, "POSTGRES_MIGRATION_PASSWORD"),
        ({"BLACKBREAD_RUNTIME_DB_PASSWORD": None}, "BLACKBREAD_RUNTIME_DB_PASSWORD"),
        ({"BLACKBREAD_RUNTIME_DB_PASSWORD": ""}, "BLACKBREAD_RUNTIME_DB_PASSWORD"),
    ],
)
def test_compose_fails_closed_on_missing_or_empty_credential(
    override: dict[str, str | None], expected_variable: str
) -> None:
    result = compose_config(compose_env(**override))
    assert result.returncode != 0
    assert expected_variable in result.stderr


def test_compose_accepts_supplied_credentials_without_rendering_them() -> None:
    result = compose_config(compose_env())
    assert result.returncode == 0
    # --quiet validates without emitting rendered configuration containing credentials.
    assert result.stdout.strip() == ""


def test_compose_passes_db_components_and_never_renders_a_dsn() -> None:
    """api and migrate receive user/password/host/port/name as separate settings.

    No service environment may contain a pre-rendered BLACKBREAD_DATABASE_URL:
    interpolating the raw password into a URL string silently misparses values
    containing reserved characters. Passwords stay raw; only the application
    layer may build the SQLAlchemy URL.
    """
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    api_env = services["api"]["environment"]
    migrate_env = services["migrate"]["environment"]

    for env in (api_env, migrate_env):
        assert "BLACKBREAD_DATABASE_URL" not in env
        assert env["BLACKBREAD_DB_HOST"] == "database"
        assert env["BLACKBREAD_DB_NAME"] == "blackbread"
        assert env["BLACKBREAD_DB_PORT"] in ("5432", 5432)
        # Passwords are interpolated raw and fail closed: required, never a default.
        assert ":?" in env["BLACKBREAD_DB_PASSWORD"]
        assert ":-" not in env["BLACKBREAD_DB_PASSWORD"]

    assert api_env["BLACKBREAD_DB_USER"] == "blackbread_app"
    assert api_env["BLACKBREAD_DB_PASSWORD"].startswith("${BLACKBREAD_RUNTIME_DB_PASSWORD")
    assert migrate_env["BLACKBREAD_DB_USER"] == "blackbread_migration"
    assert migrate_env["BLACKBREAD_DB_PASSWORD"].startswith("${POSTGRES_MIGRATION_PASSWORD")
