"""Runtime configuration, read from environment / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./scraper.db"
    admin_api_key: str = ""
    approved_participants_csv: str = "./approved_participants.csv"
    pairing_window_seconds: int = 900


settings = Settings()
