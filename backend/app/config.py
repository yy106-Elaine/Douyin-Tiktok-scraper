"""Runtime configuration, read from environment / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./scraper.db"
    admin_api_key: str = ""
    approved_participants_csv: str = "./approved_participants.csv"
    pairing_window_seconds: int = 900

    #: The zone every shown time and every day boundary is expressed
    #: in. Storage stays UTC; this is only what a reader sees and how
    #: "new today" is counted -- an evening run should not land on
    #: tomorrow. See app/clock.py.
    display_timezone: str = "America/New_York"

    #: YouTube Data API v3 key. Only `app.youtube` needs it, so the
    #: rest of the system runs without one.
    youtube_api_key: str = ""

    #: Search parameters for YouTube collection. These change which
    #: results the API returns, so they are part of the sampling method
    #: rather than a convenience -- kept here so the daily command
    #: stays short and the choice is recorded in one place, and stored
    #: on every row so a mid-study change is visible in the data.
    youtube_relevance_language: str = "zh-Hans"
    youtube_region_code: str = ""

    #: Where the install page sends a phone to fetch the APK. CI keeps
    #: this asset name stable, so the URL does not change per build.
    apk_download_url: str = (
        "https://github.com/yy106-Elaine/Douyin-Tiktok-scraper/releases/"
        "download/apk-latest/capture-latest.apk"
    )


settings = Settings()
