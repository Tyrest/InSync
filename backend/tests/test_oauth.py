from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from app.core.security import create_access_token
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.app_config import AppConfig
from app.models.platform_link import PlatformLink
from app.models.user import User
from app.state import app_state
from fastapi.testclient import TestClient
from sqlalchemy import select

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def _create_user() -> User:
    with SessionLocal() as db:
        suffix = uuid4().hex[:8]
        user = User(
            jellyfin_user_id=f"jf-user-{suffix}",
            jellyfin_username=f"tester-{suffix}",
            is_admin=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _set_spotify_oauth_config() -> None:
    with SessionLocal() as db:
        for key, value in {
            "spotify_client_id": "spotify-client-id",
            "spotify_client_secret": "spotify-client-secret",
        }.items():
            row = db.scalar(select(AppConfig).where(AppConfig.key == key))
            if row:
                row.value = value
            else:
                db.add(AppConfig(key=key, value=value))
        db.commit()


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


def test_start_spotify_oauth_returns_authorize_url() -> None:
    user = _create_user()
    _set_spotify_oauth_config()
    response = client.get("/api/platforms/spotify/oauth/start", headers=_auth_headers(user))
    assert response.status_code == 200
    body = response.json()
    assert "authorize_url" in body
    assert "accounts.spotify.com/authorize" in body["authorize_url"]


def test_callback_spotify_persists_link() -> None:
    user = _create_user()
    _set_spotify_oauth_config()
    start = client.get("/api/platforms/spotify/oauth/start", headers=_auth_headers(user))
    parsed = urlparse(start.json()["authorize_url"])
    state = parse_qs(parsed.query)["state"][0]

    async def fake_complete_auth(**kwargs) -> dict:
        _ = kwargs
        return {
            "access_token": "new-token",
            "refresh_token": "refresh-token",
            "expires_at": 9999999999,
        }

    connector = app_state.registry.get("spotify")
    original = connector.complete_auth
    connector.complete_auth = fake_complete_auth  # type: ignore[assignment]
    try:
        callback = client.get(
            f"/api/platforms/spotify/oauth/callback?code=abc&state={state}",
            follow_redirects=False,
        )
        assert callback.status_code == 302
        assert "oauth_status=success" in callback.headers["location"]
    finally:
        connector.complete_auth = original  # type: ignore[assignment]

    with SessionLocal() as db:
        link = db.scalar(
            select(PlatformLink).where(PlatformLink.user_id == user.id, PlatformLink.platform == "spotify")
        )
        assert link is not None
        assert "new-token" in link.credentials_json
