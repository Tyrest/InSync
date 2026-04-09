from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.database import get_db
from app.models.app_config import AppConfig
from app.models.user import User
from app.state import app_state

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict[str, str | bool]:
    configured = db.scalar(select(AppConfig).where(AppConfig.key == "jellyfin_url")) and db.scalar(
        select(AppConfig).where(AppConfig.key == "jellyfin_api_key")
    )
    if not configured:
        raise HTTPException(status_code=400, detail="Server setup is incomplete")

    try:
        auth = await app_state.jellyfin.authenticate(payload.username, payload.password)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"Jellyfin auth failed: {exc}") from exc

    jellyfin_user = auth["User"]
    existing = db.scalar(select(User).where(User.jellyfin_user_id == str(jellyfin_user["Id"])))
    if not existing:
        total_users = db.scalar(select(func.count(User.id))) or 0
        existing = User(
            jellyfin_user_id=str(jellyfin_user["Id"]),
            jellyfin_username=jellyfin_user.get("Name", payload.username),
            is_admin=(total_users == 0),
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)

    token = create_access_token(
        subject=existing.jellyfin_username,
        extra={"uid": existing.id, "jellyfin_user_id": existing.jellyfin_user_id, "is_admin": existing.is_admin},
    )
    return {"access_token": token, "is_admin": existing.is_admin}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)) -> dict[str, str | bool]:
    return {
        "id": str(current_user.id),
        "jellyfin_user_id": current_user.jellyfin_user_id,
        "username": current_user.jellyfin_username,
        "is_admin": current_user.is_admin,
    }
