from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.download_task import DownloadTask
from app.models.platform_link import PlatformLink
from app.models.synced_playlist import SyncedPlaylist, SyncedPlaylistTrack
from app.models.user import User
from app.state import app_state

router = APIRouter()


@router.get("/summary")
def dashboard_summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    track_count = (
        db.scalar(
            select(func.count(func.distinct(SyncedPlaylistTrack.track_id)))
            .select_from(SyncedPlaylistTrack)
            .join(SyncedPlaylist, SyncedPlaylist.id == SyncedPlaylistTrack.synced_playlist_id)
            .where(SyncedPlaylist.user_id == current_user.id)
        )
        or 0
    )

    playlist_total = (
        db.scalar(select(func.count()).select_from(SyncedPlaylist).where(SyncedPlaylist.user_id == current_user.id))
        or 0
    )
    playlist_enabled = (
        db.scalar(
            select(func.count())
            .select_from(SyncedPlaylist)
            .where(SyncedPlaylist.user_id == current_user.id, SyncedPlaylist.enabled.is_(True))
        )
        or 0
    )
    platform_links = (
        db.scalar(select(func.count()).select_from(PlatformLink).where(PlatformLink.user_id == current_user.id)) or 0
    )

    last_completed = db.scalar(
        select(func.max(DownloadTask.completed_at)).where(DownloadTask.user_id == current_user.id)
    )

    next_sync: str | None = None
    if app_state.scheduler:
        nrt = app_state.scheduler.next_run_time()
        if nrt:
            next_sync = nrt.isoformat()

    return {
        "tracks_in_library": track_count,
        "synced_playlists_total": playlist_total,
        "synced_playlists_enabled": playlist_enabled,
        "platform_links": platform_links,
        "last_completed_download": last_completed.isoformat() if last_completed else None,
        "next_sync": next_sync,
    }
