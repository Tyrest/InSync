# Feature: backend-refactor, Property 5
"""Property tests for app_config service — set_setting upsert idempotency.

Validates: Requirements 4.1, 4.2, 4.3, 4.5
"""

from app.database import Base
from app.models.app_config import AppConfig
from app.services.app_config import set_setting
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    return SessionLocal()


@given(
    key=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))),
    value1=st.text(max_size=100),
    value2=st.text(max_size=100),
)
@settings(max_examples=100)
def test_set_setting_upsert_is_idempotent(key: str, value1: str, value2: str) -> None:
    """Property 5: calling set_setting twice for the same key leaves exactly one row
    holding the second value (upsert semantics are idempotent).

    **Validates: Requirements 4.1, 4.2, 4.3, 4.5**
    """
    db = _make_session()
    try:
        set_setting(db, key, value1)
        db.flush()

        set_setting(db, key, value2)
        db.flush()

        row_count = db.scalar(select(func.count()).select_from(AppConfig).where(AppConfig.key == key))
        assert row_count == 1, f"Expected exactly 1 row for key {key!r}, got {row_count}"

        stored_value = db.scalar(select(AppConfig.value).where(AppConfig.key == key))
        assert stored_value == value2, f"Expected stored value {value2!r} for key {key!r}, got {stored_value!r}"
    finally:
        db.close()
