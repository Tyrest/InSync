import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from app.config import get_settings


def _jwt_secret() -> str:
    settings = get_settings()
    secret = settings.jwt_secret.strip() if settings.jwt_secret else ""
    if not secret:
        # Keep zero-config behavior for pre-startup token operations (e.g. tests);
        # app startup persists the resolved value into app_config.
        secret = secrets.token_urlsafe(48)
        settings.jwt_secret = secret
    return secret


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_exp_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _jwt_secret(), algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, _jwt_secret(), algorithms=[settings.jwt_algorithm])  # type: ignore[no-any-return]
