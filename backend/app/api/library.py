from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.synced_playlist import SyncedPlaylist, SyncedPlaylistTrack
from app.models.track import Track
from app.models.user import User

router = APIRouter()


@router.get("/tracks")
def list_downloaded_tracks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    q: str | None = None,
    limit: int = Query(100, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> dict:
    """Tracks that appear on this user's synced playlists (i.e. mirrored into their library)."""
    user_track_ids = (
        select(SyncedPlaylistTrack.track_id)
        .join(SyncedPlaylist, SyncedPlaylist.id == SyncedPlaylistTrack.synced_playlist_id)
        .where(SyncedPlaylist.user_id == current_user.id)
        .distinct()
    ).subquery()

    stmt = select(Track).where(Track.id.in_(select(user_track_ids.c.track_id)))
    if q and q.strip():
        pat = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Track.title.ilike(pat),
                Track.artist.ilike(pat),
                Track.album.ilike(pat),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = db.scalar(count_stmt) or 0

    stmt = stmt.order_by(Track.artist.asc(), Track.title.asc()).limit(limit).offset(offset)
    rows = db.scalars(stmt).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "tracks": [
            {
                "id": t.id,
                "title": t.title,
                "artist": t.artist,
                "album": t.album,
                "duration_seconds": t.duration_seconds,
                "source_platform": t.source_platform,
                "source_id": t.source_id,
                "file_size": t.file_size,
                "file_name": Path(t.file_path).name,
                "file_path": t.file_path,
                "created_at": t.created_at.isoformat(),
            }
            for t in rows
        ],
    }
