import secrets
from datetime import UTC, datetime, timedelta

from app.models.oauth_state import OAuthState
from sqlalchemy import delete, select
from sqlalchemy.orm import Session


def create_oauth_state(
    db: Session,
    *,
    user_id: int,
    platform: str,
    redirect_uri: str,
    code_verifier: str | None = None,
    ttl_seconds: int = 600,
) -> OAuthState:
    cleanup_expired_oauth_states(db)
    state_value = secrets.token_urlsafe(32)
    record = OAuthState(
        user_id=user_id,
        platform=platform,
        state=state_value,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def consume_oauth_state(
    db: Session, *, platform: str, state_value: str, user_id: int | None = None
) -> OAuthState | None:
    record = db.scalar(
        select(OAuthState).where(
            OAuthState.platform == platform,
            OAuthState.state == state_value,
        )
    )
    if not record:
        return None
    if user_id is not None and record.user_id != user_id:
        return None
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        db.delete(record)
        db.commit()
        return None
    db.delete(record)
    db.commit()
    return record


def cleanup_expired_oauth_states(db: Session) -> None:
    db.execute(delete(OAuthState).where(OAuthState.expires_at < datetime.now(UTC)))
    db.commit()
