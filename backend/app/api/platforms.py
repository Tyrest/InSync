import json
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.platform_link import PlatformLink
from app.models.user import User
from app.services.app_config import get_effective_setting
from app.services.oauth_state import consume_oauth_state, create_oauth_state
from app.state import app_state

router = APIRouter()


class LinkedPlatform(BaseModel):
    platform: str
    linked_at: str


class PlatformsResponse(BaseModel):
    available: list[str]
    linked: list[LinkedPlatform]


class OAuthStartResponse(BaseModel):
    authorize_url: str


class UnlinkResponse(BaseModel):
    status: str


@router.get("", response_model=PlatformsResponse)
def list_platforms(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PlatformsResponse:
    linked = db.scalars(select(PlatformLink).where(PlatformLink.user_id == current_user.id)).all()
    return PlatformsResponse(
        available=app_state.registry.all(),
        linked=[
            LinkedPlatform(
                platform=link.platform,
                linked_at=str(link.linked_at),
            )
            for link in linked
        ],
    )


def _callback_redirect_base(db: Session, request: Request) -> str:
    settings = get_settings()
    configured = get_effective_setting(db, "oauth_redirect_base_url", settings.oauth_redirect_base_url)
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


@router.get("/{platform}/oauth/start", response_model=OAuthStartResponse)
async def start_oauth(
    platform: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OAuthStartResponse:
    try:
        connector = app_state.registry.get(platform)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    client_id, _ = connector.get_credentials(db)
    if not client_id:
        raise HTTPException(status_code=400, detail=f"{platform} OAuth is not configured by admin")

    callback_base = _callback_redirect_base(db, request)
    redirect_uri = f"{callback_base}/api/platforms/{platform}/oauth/callback"
    oauth_state = create_oauth_state(
        db,
        user_id=current_user.id,
        platform=platform,
        redirect_uri=redirect_uri,
    )
    auth = await connector.start_auth(
        user_id=current_user.id,
        redirect_uri=redirect_uri,
        state=oauth_state.state,
        client_id=client_id,
    )
    return OAuthStartResponse(authorize_url=auth["authorize_url"])


@router.get("/{platform}/oauth/callback")
async def complete_oauth_callback(
    platform: str,
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    callback_base = _callback_redirect_base(db, request)
    frontend_path = f"{callback_base}/platforms"

    if error:
        params = urlencode(
            {
                "oauth_platform": platform,
                "oauth_status": "error",
                "oauth_message": error_description or error,
            }
        )
        return RedirectResponse(f"{frontend_path}?{params}", status_code=302)

    if not state or not code:
        params = urlencode(
            {
                "oauth_platform": platform,
                "oauth_status": "error",
                "oauth_message": "Missing code or state in callback",
            }
        )
        return RedirectResponse(f"{frontend_path}?{params}", status_code=302)

    oauth_state = consume_oauth_state(db, platform=platform, state_value=state)
    if not oauth_state:
        params = urlencode(
            {
                "oauth_platform": platform,
                "oauth_status": "error",
                "oauth_message": "OAuth state is invalid or expired",
            }
        )
        return RedirectResponse(f"{frontend_path}?{params}", status_code=302)

    try:
        connector = app_state.registry.get(platform)
    except KeyError as exc:
        params = urlencode(
            {
                "oauth_platform": platform,
                "oauth_status": "error",
                "oauth_message": str(exc),
            }
        )
        return RedirectResponse(f"{frontend_path}?{params}", status_code=302)

    client_id, client_secret = connector.get_credentials(db)
    if not client_id or not client_secret:
        params = urlencode(
            {
                "oauth_platform": platform,
                "oauth_status": "error",
                "oauth_message": f"{platform} OAuth is not configured by admin",
            }
        )
        return RedirectResponse(f"{frontend_path}?{params}", status_code=302)

    try:
        credentials = await connector.complete_auth(
            user_id=oauth_state.user_id,
            callback_data={"code": code},
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=oauth_state.redirect_uri,
            code_verifier=oauth_state.code_verifier,
        )
    except Exception as exc:  # noqa: BLE001
        params = urlencode(
            {
                "oauth_platform": platform,
                "oauth_status": "error",
                "oauth_message": f"OAuth token exchange failed: {exc}",
            }
        )
        return RedirectResponse(f"{frontend_path}?{params}", status_code=302)

    existing = db.scalar(
        select(PlatformLink).where(
            PlatformLink.user_id == oauth_state.user_id,
            PlatformLink.platform == platform,
        )
    )
    if existing:
        existing.credentials_json = json.dumps(credentials)
    else:
        db.add(
            PlatformLink(
                user_id=oauth_state.user_id,
                platform=platform,
                credentials_json=json.dumps(credentials),
            )
        )
    db.commit()

    params = urlencode(
        {
            "oauth_platform": platform,
            "oauth_status": "success",
            "oauth_message": f"{platform} account linked",
        }
    )
    return RedirectResponse(f"{frontend_path}?{params}", status_code=302)


@router.delete("/{platform}/link", response_model=UnlinkResponse)
def unlink_platform(
    platform: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UnlinkResponse:
    link = db.scalar(
        select(PlatformLink).where(
            PlatformLink.user_id == current_user.id,
            PlatformLink.platform == platform,
        )
    )
    if not link:
        raise HTTPException(status_code=404, detail="Not linked")
    db.delete(link)
    db.commit()
    return UnlinkResponse(status="unlinked")
