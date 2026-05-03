from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.app_config import get_db_setting, set_setting
from app.state import app_state

router = APIRouter()


class SetupRequest(BaseModel):
    jellyfin_url: HttpUrl
    jellyfin_api_key: str


class SetupResponse(BaseModel):
    status: str


class SetupStatusResponse(BaseModel):
    configured: bool


@router.post("", response_model=SetupResponse)
async def configure_setup(payload: SetupRequest, db: Session = Depends(get_db)) -> SetupResponse:
    app_state.jellyfin.base_url = str(payload.jellyfin_url).rstrip("/")
    app_state.jellyfin.api_key = payload.jellyfin_api_key
    try:
        await app_state.jellyfin.validate_server()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to validate Jellyfin: {exc}") from exc

    set_setting(db, "jellyfin_url", str(payload.jellyfin_url))
    set_setting(db, "jellyfin_api_key", payload.jellyfin_api_key)
    db.commit()
    return SetupResponse(status="ok")


@router.get("", response_model=SetupStatusResponse)
def setup_status(db: Session = Depends(get_db)) -> SetupStatusResponse:
    jellyfin_url = get_db_setting(db, "jellyfin_url")
    jellyfin_api_key = get_db_setting(db, "jellyfin_api_key")
    return SetupStatusResponse(configured=bool(jellyfin_url and jellyfin_api_key))
