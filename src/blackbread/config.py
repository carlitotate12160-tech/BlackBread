from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BLACKBREAD_",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+asyncpg://blackbread_app:blackbread-runtime@localhost:5432/blackbread"
    )
    artifact_root: Path = Path("artifacts")
    artifact_key: SecretStr


@lru_cache
def get_settings() -> Settings:
    return Settings.model_validate({})
