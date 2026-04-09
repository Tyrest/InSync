import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.services.app_config import get_effective_setting
from app.services.sync_engine import SyncEngine
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def resolve_server_timezone(db: Session | None = None) -> ZoneInfo:
    """Return the configured server timezone with precedence: DB > env > host local > UTC."""
    if db is not None:
        db_val = get_effective_setting(db, "server_timezone")
        if db_val:
            try:
                return ZoneInfo(db_val)
            except (ZoneInfoNotFoundError, KeyError):
                log.warning("Invalid IANA timezone in DB: %s; falling back", db_val)

    settings = get_settings()
    env_val = settings.server_timezone
    if env_val:
        try:
            return ZoneInfo(env_val)
        except (ZoneInfoNotFoundError, KeyError):
            log.warning("Invalid IANA timezone in env: %s; falling back", env_val)

    try:
        local_tz = datetime.now().astimezone().tzinfo
        if local_tz is not None:
            name = str(local_tz)
            if "/" in name:
                return ZoneInfo(name)
    except Exception:
        pass

    return ZoneInfo("UTC")


class SchedulerService:
    def __init__(self, sync_engine: SyncEngine, db_factory=None) -> None:
        self.sync_engine = sync_engine
        self._db_factory = db_factory
        tz = self._resolve_tz()
        self._tz = tz
        self.scheduler = AsyncIOScheduler(timezone=tz)

    def _resolve_tz(self) -> ZoneInfo:
        if self._db_factory is not None:
            db: Session = self._db_factory()
            try:
                return resolve_server_timezone(db)
            finally:
                db.close()
        return resolve_server_timezone()

    async def _run_daily_sync(self) -> None:
        log.info("Cron job daily_sync started (tz=%s)", self._tz)
        try:
            await self.sync_engine.run_all_users_sync()
        except Exception:
            log.exception("Cron job daily_sync failed")
            raise
        log.info("Cron job daily_sync completed")

    def start(self) -> None:
        settings = get_settings()
        trigger = CronTrigger(hour=settings.sync_hour_utc, minute=0, timezone=self._tz)
        self.scheduler.add_job(self._run_daily_sync, trigger=trigger, id="daily_sync")
        self.scheduler.start()
        log.info("Scheduler started: daily_sync at %s:00 (%s)", settings.sync_hour_utc, self._tz)

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def next_run_time(self) -> datetime | None:
        job = self.scheduler.get_job("daily_sync")
        return job.next_run_time if job else None

    def reschedule(self) -> None:
        """Re-read timezone + hour from config and reschedule the daily sync job."""
        self._tz = self._resolve_tz()
        settings = get_settings()
        trigger = CronTrigger(hour=settings.sync_hour_utc, minute=0, timezone=self._tz)
        self.scheduler.reschedule_job("daily_sync", trigger=trigger)
        log.info("Scheduler rescheduled: daily_sync at %s:00 (%s)", settings.sync_hour_utc, self._tz)
