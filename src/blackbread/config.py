from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BLACKBREAD_",
        extra="ignore",
    )

    # Required with no default: a repository-known database URL would embed a
    # usable credential and let any control-plane process authenticate as
    # blackbread_app. Deployment must supply a non-empty value; an unset or empty
    # BLACKBREAD_DATABASE_URL fails closed instead of selecting a fallback.
    database_url: str = Field(min_length=1)
    artifact_root: Path = Path("artifacts")
    artifact_key: SecretStr


@lru_cache
def get_settings() -> Settings:
    return Settings.model_validate({})
