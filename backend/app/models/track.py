from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(512))
    artist: Mapped[str] = mapped_column(String(512))
    album: Mapped[str] = mapped_column(String(512), default="Singles")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(String(1024), unique=True)
    source_platform: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
