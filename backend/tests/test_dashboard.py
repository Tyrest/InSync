"""Tests for dashboard summary API."""

from uuid import uuid4

from app.core.security import create_access_token
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.user import User
from fastapi.testclient import TestClient

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def _create_user() -> User:
    with SessionLocal() as db:
        suffix = uuid4().hex[:8]
        user = User(
            jellyfin_user_id=f"jf-dash-{suffix}",
            jellyfin_username=f"dasher-{suffix}",
            is_admin=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(
        subject=user.jellyfin_username,
        extra={
            "uid": user.id,
            "jellyfin_user_id": user.jellyfin_user_id,
            "is_admin": user.is_admin,
        },
    )
    return {"Authorization": f"Bearer {token}"}


def test_summary_returns_expected_keys() -> None:
    user = _create_user()
    resp = client.get("/api/dashboard/summary", headers=_auth_headers(user))
    assert resp.status_code == 200
    body = resp.json()
    assert "tracks_in_library" in body
    assert "synced_playlists_total" in body
    assert "synced_playlists_enabled" in body
    assert "platform_links" in body
    assert "last_completed_download" in body
    assert "next_sync" in body


def test_summary_empty_user_returns_zeros() -> None:
    user = _create_user()
    resp = client.get("/api/dashboard/summary", headers=_auth_headers(user))
    body = resp.json()
    assert body["tracks_in_library"] == 0
    assert body["synced_playlists_total"] == 0
    assert body["platform_links"] == 0


def test_sync_status_includes_next_sync() -> None:
    user = _create_user()
    resp = client.get("/api/sync/status", headers=_auth_headers(user))
    assert resp.status_code == 200
    body = resp.json()
    assert "next_sync" in body
