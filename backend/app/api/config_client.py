from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.app_config import AppConfig

router = APIRouter()


@router.get("/config/client")
def get_client_config(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    settings = get_settings()
    jellyfin_url = db.scalar(select(AppConfig).where(AppConfig.key == "jellyfin_url"))
    jellyfin_api_key = db.scalar(select(AppConfig).where(AppConfig.key == "jellyfin_api_key"))
    return {
        "baseUrl": settings.normalized_base_url,
        "isConfigured": bool(jellyfin_url and jellyfin_api_key),
    }
