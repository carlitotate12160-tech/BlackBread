from functools import lru_cache
from pathlib import Path
from typing import Self, cast

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

_DB_DRIVER = "postgresql+asyncpg"
_DB_COMPONENT_NAMES = ("db_user", "db_password", "db_host", "db_port", "db_name")


def _db_component_present(value: object) -> bool:
    """A component counts as supplied only when it is a non-empty value."""
    if value is None:
        return False
    if isinstance(value, SecretStr):
        return value.get_secret_value() != ""
    return value != ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BLACKBREAD_",
        extra="ignore",
    )

    # Database access resolves to exactly one of two sources, never a blend:
    #
    # * database_url (BLACKBREAD_DATABASE_URL) — an explicit postgresql+asyncpg
    #   URL for test/development use. It has no default: a repository-known URL
    #   would embed a usable credential and let any control-plane process
    #   authenticate as blackbread_app.
    # * the component set BLACKBREAD_DB_USER / _DB_PASSWORD / _DB_HOST /
    #   _DB_PORT / _DB_NAME — the production path Compose supplies. The URL is
    #   built only via sqlalchemy.engine.URL.create so a password containing
    #   reserved characters is preserved verbatim; the server-side password is
    #   never percent-encoded and never rendered into a string here.
    database_url: SecretStr | None = None
    db_user: str | None = None
    db_password: SecretStr | None = None
    db_host: str | None = None
    db_port: int | None = None
    db_name: str | None = None
    artifact_root: Path = Path("artifacts")
    artifact_key: SecretStr

    @model_validator(mode="after")
    def _require_exactly_one_database_source(self) -> Self:
        url = self.database_url.get_secret_value() if self.database_url else None
        raw = (self.db_user, self.db_password, self.db_host, self.db_port, self.db_name)
        supplied = [
            name
            for name, value in zip(_DB_COMPONENT_NAMES, raw, strict=True)
            if _db_component_present(value)
        ]
        if url and supplied:
            raise ValueError(
                "ambiguous database configuration: set BLACKBREAD_DATABASE_URL or "
                "the BLACKBREAD_DB_* component set, never both"
            )
        if url is not None:
            if url == "":
                raise ValueError("BLACKBREAD_DATABASE_URL must be non-empty")
            try:
                parsed = make_url(url)
            except Exception as error:
                raise ValueError(
                    "BLACKBREAD_DATABASE_URL must be a valid postgresql+asyncpg URL"
                ) from error
            if parsed.drivername != _DB_DRIVER:
                raise ValueError(
                    f"BLACKBREAD_DATABASE_URL must use {_DB_DRIVER}, got {parsed.drivername}"
                )
            return self
        missing = [name for name in _DB_COMPONENT_NAMES if name not in supplied]
        if missing:
            raise ValueError(
                "incomplete database configuration: supply BLACKBREAD_DATABASE_URL "
                "or all of "
                + ", ".join(f"BLACKBREAD_{name.upper()}" for name in _DB_COMPONENT_NAMES)
                + f" (missing: {', '.join(missing)})"
            )
        return self

    def sqlalchemy_url(self) -> URL:
        """Resolve the database URL as an object; the password is never rendered."""
        if self.database_url is not None:
            return make_url(self.database_url.get_secret_value())
        # The model validator above guarantees the component set is complete here.
        return URL.create(
            _DB_DRIVER,
            username=cast(str, self.db_user),
            password=cast(SecretStr, self.db_password).get_secret_value(),
            host=cast(str, self.db_host),
            port=cast(int, self.db_port),
            database=cast(str, self.db_name),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.model_validate({})
