from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_SPONSORBLOCK_CATEGORIES: frozenset[str] = frozenset(
    {"sponsor", "intro", "outro", "selfpromo", "interaction", "music_offtopic", "filler"}
)


def _normalize_base_url(base_url: str) -> str:
    if not base_url:
        return "/"
    if not base_url.startswith("/"):
        base_url = f"/{base_url}"
    if len(base_url) > 1 and base_url.endswith("/"):
        base_url = base_url[:-1]
    return base_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_host: str = "0.0.0.0"
    app_port: int = 8080
    base_url: str = "/"
    data_dir: Path = Path("./data")
    music_dir: Path = Path("./music")
    database_url: str | None = None
    jwt_secret: str = Field(default_factory=lambda: "")
    jwt_algorithm: str = "HS256"
    jwt_exp_minutes: int = 60
    jellyfin_url: AnyHttpUrl | None = None
    jellyfin_api_key: str | None = None
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    oauth_redirect_base_url: str | None = None
    download_concurrency: int = 3
    sync_hour: int = 2
    log_level: str = "INFO"
    server_timezone: str = "America/New_York"
    audio_format: str = "opus"
    audio_quality: str = "128"
    sponsorblock_enabled: bool = False
    sponsorblock_categories: str = "sponsor,intro,outro,selfpromo"

    @computed_field
    @property
    def normalized_base_url(self) -> str:
        return _normalize_base_url(self.base_url)

    @computed_field
    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = self.data_dir / "music_sync.sqlite3"
        return f"sqlite:///{db_path}"

    @computed_field
    @property
    def sponsorblock_category_list(self) -> list[str]:
        """Parsed and validated list of SponsorBlock categories."""
        if not self.sponsorblock_categories.strip():
            return []
        categories = [c.strip() for c in self.sponsorblock_categories.split(",") if c.strip()]
        unknown = [c for c in categories if c not in VALID_SPONSORBLOCK_CATEGORIES]
        if unknown:
            raise ValueError(
                f"Invalid SponsorBlock categories: {unknown}. Valid values are: {sorted(VALID_SPONSORBLOCK_CATEGORIES)}"
            )
        return categories


@lru_cache
def get_settings() -> Settings:
    return Settings()
