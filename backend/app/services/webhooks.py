"""Best-effort webhook notifications for sync events."""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

import httpx
from app.services.app_config import get_db_setting
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


async def fire_sync_webhook(
    db_factory,
    *,
    user_id: int,
    username: str,
    event: str,
    playlists_synced: int = 0,
    tracks_downloaded: int = 0,
    failures: int = 0,
) -> None:
    db: Session = db_factory()
    try:
        url = get_db_setting(db, "webhook_url")
        if not url:
            return
        enabled_csv = get_db_setting(db, "webhook_events") or "sync_complete,sync_failed"
        enabled = {e.strip() for e in enabled_csv.split(",") if e.strip()}
        if event not in enabled:
            return
        secret = get_db_setting(db, "webhook_secret") or ""
    finally:
        db.close()

    payload = {
        "event": event,
        "timestamp": datetime.now(UTC).isoformat(),
        "user_id": user_id,
        "username": username,
        "playlists_synced": playlists_synced,
        "tracks_downloaded": tracks_downloaded,
        "failures": failures,
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        body = json.dumps(payload, separators=(",", ":")).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = sig

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
            log.info("Webhook POST %s → %s", url, resp.status_code)
    except Exception:
        log.warning("Webhook POST to %s failed (best-effort)", url, exc_info=True)
