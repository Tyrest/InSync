from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.app_config import AppConfig
from app.platforms.registry import PlatformRegistry
from app.services.app_config import get_effective_setting
from app.services.download import AudioConfig, DownloadService
from app.services.jellyfin import JellyfinClient
from app.services.sync_engine import SyncEngine

if TYPE_CHECKING:
    from app.core.scheduler import SchedulerService


class AppState:
    def __init__(self) -> None:
        settings = get_settings()
        self.registry = PlatformRegistry()
        ac = AudioConfig(format=settings.audio_format, quality=settings.audio_quality)
        self.downloader = DownloadService(settings.music_dir, settings.download_concurrency, ac)
        jellyfin_url = str(settings.jellyfin_url) if settings.jellyfin_url else ""
        self.jellyfin = JellyfinClient(jellyfin_url, settings.jellyfin_api_key)
        self.sync_engine = SyncEngine(SessionLocal, self.registry, self.downloader, self.jellyfin)
        self.scheduler: SchedulerService | None = None

    def hydrate_jellyfin_from_db(self, db: Session) -> None:
        jellyfin_url = db.scalar(select(AppConfig).where(AppConfig.key == "jellyfin_url"))
        jellyfin_api_key = db.scalar(select(AppConfig).where(AppConfig.key == "jellyfin_api_key"))
        if jellyfin_url and jellyfin_api_key:
            self.jellyfin.base_url = jellyfin_url.value.rstrip("/")
            self.jellyfin.api_key = jellyfin_api_key.value

    def hydrate_audio_config_from_db(self, db: Session) -> None:
        fmt = get_effective_setting(db, "audio_format")
        quality = get_effective_setting(db, "audio_quality")
        if fmt:
            self.downloader.audio_config.format = fmt
        if quality:
            self.downloader.audio_config.quality = quality

    def seed_jellyfin_from_env_if_db_incomplete(self, db: Session) -> None:
        """Persist Jellyfin URL + API key from env when DB rows are missing (Docker rebuild + volume)."""
        settings = get_settings()
        if not settings.jellyfin_url or not settings.jellyfin_api_key:
            return
        url_row = db.scalar(select(AppConfig).where(AppConfig.key == "jellyfin_url"))
        key_row = db.scalar(select(AppConfig).where(AppConfig.key == "jellyfin_api_key"))
        if url_row and key_row:
            return
        url_value = str(settings.jellyfin_url).rstrip("/")
        key_value = settings.jellyfin_api_key
        if url_row:
            url_row.value = url_value
        else:
            db.add(AppConfig(key="jellyfin_url", value=url_value))
        if key_row:
            key_row.value = key_value
        else:
            db.add(AppConfig(key="jellyfin_api_key", value=key_value))
        db.commit()


app_state = AppState()
