"""Production Settings must carry no repository-known database credential.

The database connection is configured in exactly one of two modes, and both are
reject-on-ambiguity:

* ``BLACKBREAD_DATABASE_URL`` — an explicit, full ``postgresql+asyncpg`` URL for
  test/development use (test bootstrap and non-Compose runs);
* the component set ``BLACKBREAD_DB_USER`` / ``BLACKBREAD_DB_PASSWORD`` /
  ``BLACKBREAD_DB_HOST`` / ``BLACKBREAD_DB_PORT`` / ``BLACKBREAD_DB_NAME`` — the
  production path Compose supplies, assembled only via
  ``sqlalchemy.engine.URL.create`` so a password containing reserved characters
  is preserved verbatim and never embedded in a rendered string.

Missing, empty, partial, or simultaneously supplied configuration fails closed.
Only synthetic, non-authenticating values appear here; no real secret is used.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from blackbread.config import Settings

# A synthetic, password-free URL. It never reaches a live database and carries no secret.
_SYNTHETIC_URL = "postgresql+asyncpg://blackbread_app@127.0.0.1:5432/blackbread_test"
_SYNTHETIC_ARTIFACT_KEY = "placeholder-artifact-key"

_COMPONENTS = {
    "db_user": "blackbread_app",
    "db_password": "syn_pw",
    "db_host": "database",
    "db_port": 5432,
    "db_name": "blackbread",
}

_DB_ENV_NAMES = (
    "BLACKBREAD_DATABASE_URL",
    "BLACKBREAD_DB_USER",
    "BLACKBREAD_DB_PASSWORD",
    "BLACKBREAD_DB_HOST",
    "BLACKBREAD_DB_PORT",
    "BLACKBREAD_DB_NAME",
)


@pytest.fixture(autouse=True)
def _clean_db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from ambient database settings (env or conftest bootstrap)."""
    for name in _DB_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def _component_settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,
        artifact_key=_SYNTHETIC_ARTIFACT_KEY,
        **{**_COMPONENTS, **overrides},
    )


def test_missing_database_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No URL and no components at all must not produce a usable configuration."""
    for name in ("BLACKBREAD_DATABASE_URL", "BLACKBREAD_DB_USER", "BLACKBREAD_DB_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError):
        # _env_file=None disables .env loading; artifact_key is supplied so the
        # only unmet requirement is the database configuration.
        Settings(_env_file=None, artifact_key=_SYNTHETIC_ARTIFACT_KEY)


def test_empty_database_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicitly empty URL must not be accepted as a usable configuration."""
    monkeypatch.delenv("BLACKBREAD_DB_USER", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="", artifact_key=_SYNTHETIC_ARTIFACT_KEY)


def test_explicit_database_url_is_accepted() -> None:
    """An explicit, supplied URL configures the test/development alternative."""
    settings = Settings(
        _env_file=None,
        database_url=_SYNTHETIC_URL,
        artifact_key=_SYNTHETIC_ARTIFACT_KEY,
    )
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value() == _SYNTHETIC_URL
    assert settings.sqlalchemy_url().drivername == "postgresql+asyncpg"


def test_non_asyncpg_database_url_is_rejected() -> None:
    """The URL alternative must be a postgresql+asyncpg URL, not arbitrary input."""
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="sqlite:///blackbread.db",
            artifact_key=_SYNTHETIC_ARTIFACT_KEY,
        )


def test_component_mode_builds_url_object() -> None:
    """The component set builds the URL via URL.create with a verbatim password."""
    settings = _component_settings()
    url = settings.sqlalchemy_url()
    assert url.drivername == "postgresql+asyncpg"
    assert url.username == "blackbread_app"
    assert url.password == _COMPONENTS["db_password"]
    assert url.host == "database"
    assert url.port == 5432
    assert url.database == "blackbread"


def test_component_mode_preserves_reserved_characters_verbatim() -> None:
    """A password holding : @ / ? # % must survive URL.create unencoded."""
    special = "p:a@s/s?w#o%rd"
    settings = _component_settings(db_password=special)
    url = settings.sqlalchemy_url()
    assert url.password == special


def test_partial_component_set_is_rejected() -> None:
    """An incomplete component set is incomplete configuration, not a fallback."""
    for missing in ("db_user", "db_password", "db_host", "db_port", "db_name"):
        partial = {key: value for key, value in _COMPONENTS.items() if key != missing}
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                artifact_key=_SYNTHETIC_ARTIFACT_KEY,
                **partial,
            )


def test_empty_component_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _component_settings(db_password="")


def test_url_and_components_together_are_ambiguous_and_rejected() -> None:
    """Supplying both modes at once must be rejected, never silently resolved."""
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            artifact_key=_SYNTHETIC_ARTIFACT_KEY,
            database_url=_SYNTHETIC_URL,
            **_COMPONENTS,
        )


def test_database_url_is_a_secret_value() -> None:
    """Rendered configuration never exposes the URL through model serialization."""
    settings = Settings(
        _env_file=None,
        database_url=_SYNTHETIC_URL,
        artifact_key=_SYNTHETIC_ARTIFACT_KEY,
    )
    assert isinstance(settings.database_url, SecretStr)
    assert _SYNTHETIC_URL not in repr(settings)
    assert _SYNTHETIC_URL not in str(settings)
