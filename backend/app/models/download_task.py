from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DownloadStatus(StrEnum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


class DownloadTask(Base):
    __tablename__ = "download_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    search_query: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(512))
    artist: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default=DownloadStatus.PENDING.value)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
