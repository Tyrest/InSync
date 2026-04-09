from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
if settings.effective_database_url.startswith("sqlite:///"):
    db_file = Path(settings.effective_database_url.replace("sqlite:///", "", 1))
    db_file.parent.mkdir(parents=True, exist_ok=True)
sqlite_args = {"check_same_thread": False, "timeout": 30}
engine = create_engine(settings.effective_database_url, future=True, connect_args=sqlite_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


@event.listens_for(Engine, "connect")
def set_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
    _ = connection_record
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=30000;")
    cursor.close()


def get_db() -> Generator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
