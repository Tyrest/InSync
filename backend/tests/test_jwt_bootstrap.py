"""Tests for JWT secret bootstrap behavior."""

from app.config import get_settings
from app.core.security import create_access_token, decode_access_token
from app.database import Base, SessionLocal, engine
from app.models.app_config import AppConfig
from app.state import bootstrap_jwt_secret
from sqlalchemy import select

Base.metadata.create_all(bind=engine)


def _set_db_secret(value: str | None) -> None:
    with SessionLocal() as db:
        row = db.scalar(select(AppConfig).where(AppConfig.key == "jwt_secret"))
        if value is None:
            if row:
                db.delete(row)
        elif row:
            row.value = value
        else:
            db.add(AppConfig(key="jwt_secret", value=value))
        db.commit()


def _get_db_secret() -> str | None:
    with SessionLocal() as db:
        row = db.scalar(select(AppConfig).where(AppConfig.key == "jwt_secret"))
        return row.value if row else None


def test_bootstrap_generates_and_persists_when_missing() -> None:
    settings = get_settings()
    original = settings.jwt_secret
    try:
        _set_db_secret(None)
        settings.jwt_secret = ""
        with SessionLocal() as db:
            resolved = bootstrap_jwt_secret(db)
        assert resolved
        assert len(resolved) >= 32
        assert _get_db_secret() == resolved
        assert settings.jwt_secret == resolved
    finally:
        settings.jwt_secret = original


def test_bootstrap_prefers_existing_db_secret() -> None:
    settings = get_settings()
    original = settings.jwt_secret
    try:
        _set_db_secret("db-jwt-secret")
        settings.jwt_secret = "env-jwt-secret"
        with SessionLocal() as db:
            resolved = bootstrap_jwt_secret(db)
        assert resolved == "db-jwt-secret"
        assert settings.jwt_secret == "db-jwt-secret"
    finally:
        settings.jwt_secret = original


def test_bootstrap_seeds_db_from_env_when_missing() -> None:
    settings = get_settings()
    original = settings.jwt_secret
    try:
        _set_db_secret(None)
        settings.jwt_secret = "env-jwt-secret"
        with SessionLocal() as db:
            resolved = bootstrap_jwt_secret(db)
        assert resolved == "env-jwt-secret"
        assert _get_db_secret() == "env-jwt-secret"
    finally:
        settings.jwt_secret = original


def test_token_issue_and_decode_uses_bootstrapped_secret() -> None:
    settings = get_settings()
    original = settings.jwt_secret
    try:
        _set_db_secret("stable-db-secret-which-is-long-enough-123456")
        settings.jwt_secret = ""
        with SessionLocal() as db:
            bootstrap_jwt_secret(db)

        token = create_access_token("bootstrap-user", extra={"uid": 123})
        payload = decode_access_token(token)
        assert payload["sub"] == "bootstrap-user"
        assert payload["uid"] == 123
    finally:
        settings.jwt_secret = original
