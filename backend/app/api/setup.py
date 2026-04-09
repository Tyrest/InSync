from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.app_config import AppConfig
from app.state import app_state

router = APIRouter()


class SetupRequest(BaseModel):
    jellyfin_url: HttpUrl
    jellyfin_api_key: str


@router.post("")
async def configure_setup(payload: SetupRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    app_state.jellyfin.base_url = str(payload.jellyfin_url).rstrip("/")
    app_state.jellyfin.api_key = payload.jellyfin_api_key
    try:
        await app_state.jellyfin.validate_server()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to validate Jellyfin: {exc}") from exc

    for key, value in {
        "jellyfin_url": str(payload.jellyfin_url),
        "jellyfin_api_key": payload.jellyfin_api_key,
    }.items():
        row = db.scalar(select(AppConfig).where(AppConfig.key == key))
        if row:
            row.value = value
        else:
            db.add(AppConfig(key=key, value=value))
    db.commit()
    return {"status": "ok"}


@router.get("")
def setup_status(db: Session = Depends(get_db)) -> dict[str, bool]:
    jellyfin_url = db.scalar(select(AppConfig).where(AppConfig.key == "jellyfin_url"))
    jellyfin_api_key = db.scalar(select(AppConfig).where(AppConfig.key == "jellyfin_api_key"))
    return {"configured": bool(jellyfin_url and jellyfin_api_key)}
