"""Runtime configuration, read from environment / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./scraper.db"
    admin_api_key: str = ""
    approved_participants_csv: str = "./approved_participants.csv"
    pairing_window_seconds: int = 900

    #: YouTube Data API v3 key. Only `app.youtube` needs it, so the
    #: rest of the system runs without one.
    youtube_api_key: str = ""

    #: Where the install page sends a phone to fetch the APK. CI keeps
    #: this asset name stable, so the URL does not change per build.
    apk_download_url: str = (
        "https://github.com/yy106-Elaine/Douyin-Tiktok-scraper/releases/"
        "download/apk-latest/capture-latest.apk"
    )


settings = Settings()
