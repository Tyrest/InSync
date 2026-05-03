import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
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


class SyncAccepted(BaseModel):
    status: str


class QueueCounts(BaseModel):
    pending: int = 0
    downloading: int = 0
    completed: int = 0
    failed: int = 0


class SyncStatusResponse(BaseModel):
    linked_platforms: list[str]
    queue: QueueCounts
    sync_running: bool
    download_total: int
    download_done: int
    timestamp: str
    next_sync: str | None


class DownloadFailureItem(BaseModel):
    title: str
    artist: str
    status: str
    error_message: str | None
    created_at: str
    completed_at: str | None


class DownloadFailuresResponse(BaseModel):
    total: int
    limit: int
    offset: int
    failures: list[DownloadFailureItem]


class SyncHistoryResponse(BaseModel):
    last_completed_download: str | None
    recent_downloads: list[DownloadFailureItem]


@router.post("/manual", status_code=status.HTTP_202_ACCEPTED, response_model=SyncAccepted)
async def manual_sync(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SyncAccepted:
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
    return SyncAccepted(status="accepted")


@router.get("/status", response_model=SyncStatusResponse)
def sync_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SyncStatusResponse:
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

    return SyncStatusResponse(
        linked_platforms=[link.platform for link in links],
        queue=QueueCounts(**by_status),
        sync_running=app_state.sync_engine.is_sync_running,
        download_total=total,
        download_done=done,
        timestamp=datetime.now(UTC).isoformat(),
        next_sync=next_sync,
    )


@router.get("/download-failures", response_model=DownloadFailuresResponse)
def download_failures(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DownloadFailuresResponse:
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
    return DownloadFailuresResponse(
        total=total,
        limit=limit,
        offset=offset,
        failures=[
            DownloadFailureItem(
                title=task.title,
                artist=task.artist,
                status=task.status,
                error_message=task.error_message,
                created_at=str(task.created_at),
                completed_at=str(task.completed_at) if task.completed_at else None,
            )
            for task in tasks
        ],
    )


@router.get("/history", response_model=SyncHistoryResponse)
def sync_history(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SyncHistoryResponse:
    last_completed = db.scalar(
        select(func.max(DownloadTask.completed_at)).where(DownloadTask.user_id == current_user.id)
    )
    recent_tasks = db.scalars(
        select(DownloadTask)
        .where(DownloadTask.user_id == current_user.id)
        .order_by(DownloadTask.created_at.desc())
        .limit(20)
    ).all()
    return SyncHistoryResponse(
        last_completed_download=str(last_completed) if last_completed else None,
        recent_downloads=[
            DownloadFailureItem(
                title=task.title,
                artist=task.artist,
                status=task.status,
                error_message=task.error_message,
                created_at=str(task.created_at),
                completed_at=str(task.completed_at) if task.completed_at else None,
            )
            for task in recent_tasks
        ],
    )
