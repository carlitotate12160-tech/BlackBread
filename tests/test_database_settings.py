"""Production Settings must carry no repository-known database credential.

A default ``database_url`` would embed a usable credential in the public
repository and let any control-plane process authenticate as
``blackbread_app``. These tests pin the field as required with no default and
prove that missing configuration fails closed rather than selecting a fallback.

Only synthetic, non-authenticating URLs appear here; no real secret is used.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from pydantic_core import PydanticUndefined

from blackbread.config import Settings

# A synthetic, password-free URL. It never reaches a live database and carries no secret.
_SYNTHETIC_URL = "postgresql+asyncpg://blackbread_app@127.0.0.1:5432/blackbread_test"
_SYNTHETIC_ARTIFACT_KEY = "placeholder-artifact-key"


def test_database_url_field_is_required_without_default() -> None:
    """The production model field must be required and expose no default value."""
    field = Settings.model_fields["database_url"]
    assert field.is_required()
    assert field.default is PydanticUndefined


def test_missing_database_url_is_rejected_when_environment_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With env var and env-file loading disabled, a missing URL must fail closed."""
    monkeypatch.delenv("BLACKBREAD_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError) as excinfo:
        # _env_file=None disables .env loading; artifact_key is supplied so the
        # only unmet requirement is database_url.
        Settings(_env_file=None, artifact_key=_SYNTHETIC_ARTIFACT_KEY)
    missing = {
        tuple(error["loc"]) for error in excinfo.value.errors() if error["type"] == "missing"
    }
    assert ("database_url",) in missing


def test_empty_database_url_is_rejected_when_environment_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly empty URL must not be accepted as a usable configuration."""
    monkeypatch.delenv("BLACKBREAD_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="", artifact_key=_SYNTHETIC_ARTIFACT_KEY)


def test_explicit_database_url_is_accepted() -> None:
    """An explicit, supplied URL configures the field with no fallback substitution."""
    settings = Settings(
        _env_file=None,
        database_url=_SYNTHETIC_URL,
        artifact_key=_SYNTHETIC_ARTIFACT_KEY,
    )
    assert settings.database_url == _SYNTHETIC_URL
