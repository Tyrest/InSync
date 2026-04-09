from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SyncedPlaylist(Base):
    __tablename__ = "synced_playlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    platform_playlist_id: Mapped[str] = mapped_column(String(256), index=True)
    platform_playlist_name: Mapped[str] = mapped_column(String(512))
    jellyfin_playlist_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncedPlaylistTrack(Base):
    __tablename__ = "synced_playlist_tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    synced_playlist_id: Mapped[int] = mapped_column(ForeignKey("synced_playlists.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
