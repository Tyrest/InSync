import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.synced_playlist import SyncedPlaylist
from app.models.user import User
from app.state import app_state

router = APIRouter()


class ToggleRequest(BaseModel):
    enabled: bool


class PlaylistItem(BaseModel):
    id: int
    platform: str
    name: str
    enabled: bool
    last_synced: str | None


class PlaylistsResponse(BaseModel):
    playlists: list[PlaylistItem]


class ToggleResponse(BaseModel):
    status: str


@router.get("", response_model=PlaylistsResponse)
def list_playlists(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PlaylistsResponse:
    items = db.scalars(select(SyncedPlaylist).where(SyncedPlaylist.user_id == current_user.id)).all()
    return PlaylistsResponse(
        playlists=[
            PlaylistItem(
                id=item.id,
                platform=item.platform,
                name=item.platform_playlist_name,
                enabled=item.enabled,
                last_synced=str(item.last_synced) if item.last_synced else None,
            )
            for item in items
        ]
    )


@router.patch("/{playlist_id}", response_model=ToggleResponse)
def toggle_playlist(
    playlist_id: int,
    payload: ToggleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ToggleResponse:
    item = db.scalar(
        select(SyncedPlaylist).where(
            SyncedPlaylist.id == playlist_id,
            SyncedPlaylist.user_id == current_user.id,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Playlist not found")
    item.enabled = payload.enabled
    db.commit()
    return ToggleResponse(status="ok")


@router.post("/{playlist_id}/sync", status_code=status.HTTP_202_ACCEPTED, response_model=ToggleResponse)
async def sync_playlist(
    playlist_id: int,
    current_user: User = Depends(get_current_user),
) -> ToggleResponse:
    if app_state.sync_engine.is_user_sync_running(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A sync is already running for your account.",
        )
    loop = asyncio.get_event_loop()
    loop.create_task(app_state.sync_engine.run_single_playlist_sync(current_user.id, playlist_id))
    return ToggleResponse(status="accepted")
