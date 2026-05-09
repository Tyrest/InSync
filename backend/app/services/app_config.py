from app.config import get_settings
from app.models.app_config import AppConfig
from sqlalchemy import select
from sqlalchemy.orm import Session


def get_db_setting(db: Session, key: str) -> str | None:
    row = db.scalar(select(AppConfig).where(AppConfig.key == key))
    return row.value if row else None


def get_effective_setting(db: Session, key: str, env_default: str | None = None) -> str | None:
    value = get_db_setting(db, key)
    if value is not None:
        return value
    if env_default is not None:
        return env_default
    settings = get_settings()
    return getattr(settings, key, None)


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.scalar(select(AppConfig).where(AppConfig.key == key))
    if row:
        row.value = value
    else:
        db.add(AppConfig(key=key, value=value))


def delete_setting(db: Session, key: str) -> bool:
    """Delete a setting row. Returns True if a row was deleted, False if it didn't exist."""
    row = db.scalar(select(AppConfig).where(AppConfig.key == key))
    if row:
        db.delete(row)
        return True
    return False
