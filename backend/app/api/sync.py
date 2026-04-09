import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.download_task import DownloadStatus, DownloadTask
from app.models.platform_link import PlatformLink
from app.models.user import User
from app.state import app_state

router = APIRouter()
log = logging.getLogger(__name__)


def _run_sync_in_background(user_id: int) -> None:
    """Fire-and-forget coroutine on the running event loop."""
    loop = asyncio.get_event_loop()
    loop.create_task(app_state.sync_engine.run_user_sync_by_id(user_id))


@router.post("/manual", status_code=status.HTTP_202_ACCEPTED)
async def manual_sync(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if app_state.sync_engine.is_user_sync_running(current_user.id):
        log.info("Manual sync rejected: already running (user_id=%s)", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A sync is already running for your account. Please wait and try again.",
        )
    has_links = db.scalar(select(func.count()).select_from(PlatformLink).where(PlatformLink.user_id == current_user.id))
    if not has_links:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No platforms linked. Connect a platform first before syncing.",
        )
    log.info("Manual sync accepted (async) user_id=%s", current_user.id)
    loop = asyncio.get_event_loop()
    loop.create_task(app_state.sync_engine.run_user_sync_by_id(current_user.id))
    return {"status": "accepted"}


@router.post("/playlist/{synced_playlist_id}", status_code=status.HTTP_202_ACCEPTED)
async def sync_single_playlist(
    synced_playlist_id: int,
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    if app_state.sync_engine.is_user_sync_running(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A sync is already running for your account.",
        )
    loop = asyncio.get_event_loop()
    loop.create_task(app_state.sync_engine.run_single_playlist_sync(current_user.id, synced_playlist_id))
    return {"status": "accepted"}


@router.get("/status")
def sync_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    links = db.scalars(select(PlatformLink).where(PlatformLink.user_id == current_user.id)).all()
    tasks = db.scalars(select(DownloadTask).where(DownloadTask.user_id == current_user.id)).all()
    by_status: dict[str, int] = {}
    for download_status in DownloadStatus:
        by_status[download_status.value] = sum(1 for t in tasks if t.status == download_status.value)
    total = sum(by_status.values())
    done = by_status.get(DownloadStatus.COMPLETED.value, 0) + by_status.get(DownloadStatus.FAILED.value, 0)

    next_sync: str | None = None
    if app_state.scheduler:
        nrt = app_state.scheduler.next_run_time()
        if nrt:
            next_sync = nrt.isoformat()

    return {
        "linked_platforms": [link.platform for link in links],
        "queue": by_status,
        "sync_running": app_state.sync_engine.is_sync_running,
        "download_total": total,
        "download_done": done,
        "timestamp": datetime.now(UTC).isoformat(),
        "next_sync": next_sync,
    }


@router.get("/download-failures")
def download_failures(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """Paginated list of failed download tasks for the current user."""
    filters = (
        DownloadTask.user_id == current_user.id,
        DownloadTask.status == DownloadStatus.FAILED.value,
    )
    total = db.scalar(select(func.count()).select_from(DownloadTask).where(*filters)) or 0
    tasks = db.scalars(
        select(DownloadTask)
        .where(*filters)
        .order_by(DownloadTask.completed_at.desc(), DownloadTask.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "failures": [
            {
                "title": task.title,
                "artist": task.artist,
                "status": task.status,
                "error_message": task.error_message,
                "created_at": str(task.created_at),
                "completed_at": str(task.completed_at) if task.completed_at else None,
            }
            for task in tasks
        ],
    }


@router.get("/history")
def sync_history(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    last_completed = db.scalar(
        select(func.max(DownloadTask.completed_at)).where(DownloadTask.user_id == current_user.id)
    )
    recent_tasks = db.scalars(
        select(DownloadTask)
        .where(DownloadTask.user_id == current_user.id)
        .order_by(DownloadTask.created_at.desc())
        .limit(20)
    ).all()
    return {
        "last_completed_download": str(last_completed) if last_completed else None,
        "recent_downloads": [
            {
                "title": task.title,
                "artist": task.artist,
                "status": task.status,
                "error_message": task.error_message,
                "created_at": str(task.created_at),
                "completed_at": str(task.completed_at) if task.completed_at else None,
            }
            for task in recent_tasks
        ],
    }
