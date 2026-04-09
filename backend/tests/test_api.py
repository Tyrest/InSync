from app.database import Base, engine
from app.main import app
from fastapi.testclient import TestClient

Base.metadata.create_all(bind=engine)

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_client_config() -> None:
    response = client.get("/api/config/client")
    assert response.status_code == 200
    body = response.json()
    assert "baseUrl" in body
    assert "isConfigured" in body
