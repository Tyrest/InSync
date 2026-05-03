import pytest
from app.api.playlists import PlaylistsResponse
from app.api.setup import SetupStatusResponse
from app.api.sync import SyncStatusResponse
from app.core.security import create_access_token
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.user import User
from fastapi.testclient import TestClient

Base.metadata.create_all(bind=engine)

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert body["version"]


def test_client_config() -> None:
    response = client.get("/api/config/client")
    assert response.status_code == 200
    body = response.json()
    assert "baseUrl" in body
    assert "isConfigured" in body


def test_sync_single_playlist_route_removed() -> None:
    """POST /api/sync/playlist/{id} was removed; the route must not return 202."""
    response = client.post("/api/sync/playlist/1")
    # FastAPI returns 405 (Method Not Allowed) because the SPA GET catch-all matches
    # the path but not the method — either 404 or 405 confirms the endpoint is gone.
    assert response.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Feature: backend-refactor, Property 8
# Property: Route responses are deserializable into their declared response models
# Validates: Requirements 10.1, 10.2, 10.4
# ---------------------------------------------------------------------------


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Get-or-create a test user in the DB and return a valid Authorization header."""
    from sqlalchemy import select

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.jellyfin_user_id == "test-jellyfin-id-prop8"))
        if user is None:
            user = User(
                jellyfin_user_id="test-jellyfin-id-prop8",
                jellyfin_username="testuser_prop8",
                is_admin=False,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        token = create_access_token(
            subject=user.jellyfin_username,
            extra={
                "uid": user.id,
                "jellyfin_user_id": user.jellyfin_user_id,
                "is_admin": user.is_admin,
            },
        )
    return {"Authorization": f"Bearer {token}"}


def test_health_response_is_deserializable() -> None:
    """GET /health — response body contains expected fields (no response_model, tested directly)."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    # Manually validate the shape since there is no declared response_model
    assert isinstance(body.get("status"), str)
    assert isinstance(body.get("version"), str)


def test_client_config_response_is_deserializable() -> None:
    """GET /api/config/client — response body matches expected shape."""
    response = client.get("/api/config/client")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("baseUrl"), str)
    assert isinstance(body.get("isConfigured"), bool)


def test_setup_status_response_is_deserializable() -> None:
    """GET /api/setup — response is deserializable into SetupStatusResponse."""
    response = client.get("/api/setup")
    assert response.status_code == 200
    parsed = SetupStatusResponse.model_validate(response.json())
    assert isinstance(parsed.configured, bool)


def test_sync_status_response_is_deserializable(auth_headers: dict[str, str]) -> None:
    """GET /api/sync/status — response is deserializable into SyncStatusResponse."""
    response = client.get("/api/sync/status", headers=auth_headers)
    assert response.status_code == 200
    parsed = SyncStatusResponse.model_validate(response.json())
    assert isinstance(parsed.linked_platforms, list)
    assert isinstance(parsed.sync_running, bool)


def test_playlists_response_is_deserializable(auth_headers: dict[str, str]) -> None:
    """GET /api/playlists — response is deserializable into PlaylistsResponse."""
    response = client.get("/api/playlists", headers=auth_headers)
    assert response.status_code == 200
    parsed = PlaylistsResponse.model_validate(response.json())
    assert isinstance(parsed.playlists, list)
