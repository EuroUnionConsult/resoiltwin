from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ReSoilTwin API"
    environment: str = "local"
    database_url: str = "postgresql+psycopg://resoiltwin:change-me-locally@localhost:55433/resoiltwin"
    cdse_client_id: str | None = None
    cdse_client_secret: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
