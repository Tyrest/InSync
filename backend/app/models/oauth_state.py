from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    code_verifier: Mapped[str | None] = mapped_column(String(256), nullable=True)
    redirect_uri: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
