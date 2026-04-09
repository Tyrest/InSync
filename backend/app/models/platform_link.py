from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlatformLink(Base):
    __tablename__ = "platform_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    credentials_json: Mapped[str] = mapped_column(Text, default="{}")
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    last_synced: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
