"""Tests for admin secret masking."""

from uuid import uuid4

from app.core.security import create_access_token
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.app_config import AppConfig
from app.models.user import User
from fastapi.testclient import TestClient
from sqlalchemy import select

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def _create_admin() -> User:
    with SessionLocal() as db:
        suffix = uuid4().hex[:8]
        user = User(
            jellyfin_user_id=f"jf-admin-{suffix}",
            jellyfin_username=f"admin-{suffix}",
            is_admin=True,
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


def _seed_secret(key: str, value: str) -> None:
    with SessionLocal() as db:
        row = db.scalar(select(AppConfig).where(AppConfig.key == key))
        if row:
            row.value = value
        else:
            db.add(AppConfig(key=key, value=value))
        db.commit()


def test_settings_masks_secrets() -> None:
    user = _create_admin()
    _seed_secret("spotify_client_secret", "super-secret-value-1234")
    resp = client.get("/api/admin/settings", headers=_auth_headers(user))
    assert resp.status_code == 200
    body = resp.json()
    secret = body.get("spotify_client_secret", "")
    assert "1234" in secret  # last 4 chars visible
    assert "super-secret" not in secret  # rest is masked


def test_settings_effective_masks_secrets() -> None:
    user = _create_admin()
    _seed_secret("google_client_secret", "my-google-secret-5678")
    resp = client.get("/api/admin/settings/effective", headers=_auth_headers(user))
    assert resp.status_code == 200
    body = resp.json()
    val = body["values"].get("google_client_secret", "")
    assert "5678" in val
    assert "my-google" not in val
