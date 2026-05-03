from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.dependencies import require_admin
from app.database import get_db
from app.models.app_config import AppConfig
from app.models.download_task import DownloadTask
from app.models.user import User
from app.services.app_config import set_setting
from app.state import app_state, hydrate_audio_config_from_db, hydrate_jellyfin_from_db

router = APIRouter()


class UserItem(BaseModel):
    id: int
    jellyfin_user_id: str
    username: str
    is_admin: bool


class UsersResponse(BaseModel):
    users: list[UserItem]


class SystemInfoResponse(BaseModel):
    music_dir_exists: bool
    data_dir_exists: bool
    download_tasks: int
    download_concurrency: int


class AdminSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")  # dynamic keys from AppConfig


class SettingsUpdateResponse(BaseModel):
    status: str


_SECRET_KEYS = frozenset(
    {
        "spotify_client_secret",
        "google_client_secret",
        "jellyfin_api_key",
        "jwt_secret",
        "webhook_secret",
    }
)


def _mask(value: str | None) -> str | None:
    if not value:
        return value
    if len(value) <= 4:
        return "****"
    return ("*" * (len(value) - 4)) + value[-4:]


@router.get("/users", response_model=UsersResponse)
def users(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> UsersResponse:
    all_users = db.scalars(select(User)).all()
    return UsersResponse(
        users=[
            UserItem(
                id=user.id,
                jellyfin_user_id=user.jellyfin_user_id,
                username=user.jellyfin_username,
                is_admin=user.is_admin,
            )
            for user in all_users
        ]
    )


@router.get("/system", response_model=SystemInfoResponse)
def system_info(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> SystemInfoResponse:
    settings = get_settings()
    music_dir = settings.music_dir
    data_dir = settings.data_dir
    tasks = db.scalars(select(DownloadTask)).all()
    return SystemInfoResponse(
        music_dir_exists=Path(music_dir).exists(),
        data_dir_exists=Path(data_dir).exists(),
        download_tasks=len(tasks),
        download_concurrency=settings.download_concurrency,
    )


class AdminSettingsUpdate(BaseModel):
    download_concurrency: int | None = None
    sync_hour_utc: int | None = None
    jellyfin_url: str | None = None
    jellyfin_api_key: str | None = None
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    oauth_redirect_base_url: str | None = None
    server_timezone: str | None = None
    audio_format: str | None = None
    audio_quality: str | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None
    webhook_events: str | None = None


@router.get("/settings", response_model=AdminSettingsResponse)
def get_settings_view(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> AdminSettingsResponse:
    rows = db.scalars(select(AppConfig)).all()
    data = {row.key: _mask(row.value) if row.key in _SECRET_KEYS else row.value for row in rows}
    return AdminSettingsResponse(**data)


@router.get("/settings/effective")
def get_effective_settings(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    rows = db.scalars(select(AppConfig)).all()
    db_map = {row.key: row.value for row in rows}

    def source_for(key: str, env_value: str | None) -> str:
        if key in db_map:
            return "db"
        if env_value:
            return "env"
        return "unset"

    def val(key: str, env_value: str | None) -> str | None:
        raw = db_map.get(key) or env_value
        if key in _SECRET_KEYS:
            return _mask(raw)
        return raw

    effective = {
        "spotify_client_id": val("spotify_client_id", settings.spotify_client_id),
        "spotify_client_secret": val("spotify_client_secret", settings.spotify_client_secret),
        "google_client_id": val("google_client_id", settings.google_client_id),
        "google_client_secret": val("google_client_secret", settings.google_client_secret),
        "oauth_redirect_base_url": db_map.get("oauth_redirect_base_url") or settings.oauth_redirect_base_url,
        "server_timezone": db_map.get("server_timezone") or settings.server_timezone or "",
        "audio_format": db_map.get("audio_format") or settings.audio_format,
        "audio_quality": db_map.get("audio_quality") or settings.audio_quality,
    }
    sources = {
        "spotify_client_id": source_for("spotify_client_id", settings.spotify_client_id),
        "spotify_client_secret": source_for("spotify_client_secret", settings.spotify_client_secret),
        "google_client_id": source_for("google_client_id", settings.google_client_id),
        "google_client_secret": source_for("google_client_secret", settings.google_client_secret),
        "oauth_redirect_base_url": source_for("oauth_redirect_base_url", settings.oauth_redirect_base_url),
    }
    configured = {
        "spotify": bool(db_map.get("spotify_client_id") or settings.spotify_client_id)
        and bool(db_map.get("spotify_client_secret") or settings.spotify_client_secret),
        "youtube": bool(db_map.get("google_client_id") or settings.google_client_id)
        and bool(db_map.get("google_client_secret") or settings.google_client_secret),
    }
    return {"values": effective, "sources": sources, "configured": configured}


@router.patch("/settings", response_model=SettingsUpdateResponse)
def update_settings(
    payload: AdminSettingsUpdate, _: User = Depends(require_admin), db: Session = Depends(get_db)
) -> SettingsUpdateResponse:
    changes = payload.model_dump(exclude_none=True)
    for key, value in changes.items():
        set_setting(db, key, str(value))
    db.commit()

    hydrate_jellyfin_from_db(db)
    hydrate_audio_config_from_db(db)
    if app_state.scheduler and ("sync_hour_utc" in changes or "server_timezone" in changes):
        app_state.scheduler.reschedule()
    return SettingsUpdateResponse(status="ok")
