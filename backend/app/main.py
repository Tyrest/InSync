import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config import get_settings
from app.core.scheduler import SchedulerService
from app.database import Base, SessionLocal, engine
from app.logging_config import configure_logging
from app.state import app_state

settings = get_settings()
_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    _log.info(
        "Application startup (data_dir=%s, music_dir=%s, log_level=%s)",
        settings.data_dir,
        settings.music_dir,
        settings.log_level,
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.music_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        app_state.bootstrap_jwt_secret(db)
        app_state.seed_jellyfin_from_env_if_db_incomplete(db)
        app_state.hydrate_jellyfin_from_db(db)
        app_state.hydrate_audio_config_from_db(db)
    scheduler = SchedulerService(app_state.sync_engine, db_factory=SessionLocal)
    scheduler.start()
    app_state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(
    title="InSync",
    version="0.1.0",
    root_path=settings.normalized_base_url if settings.normalized_base_url != "/" else "",
    lifespan=lifespan,
)
app.include_router(api_router)

static_dir = Path(__file__).resolve().parents[1] / "static"
if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/{full_path:path}", response_model=None)
def spa(full_path: str):
    if not static_dir.exists():
        return JSONResponse({"message": f"API running (path={full_path})"})
    index = static_dir / "index.html"
    return FileResponse(index)
