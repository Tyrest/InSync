import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.models.download_task import DownloadStatus, DownloadTask
from app.models.platform_link import PlatformLink
from app.models.synced_playlist import SyncedPlaylist, SyncedPlaylistTrack
from app.models.track import Track
from app.models.user import User
from app.platforms.registry import PlatformRegistry
from app.services.app_config import get_effective_setting
from app.services.download import DownloadRequest, DownloadResult, DownloadService
from app.services.jellyfin import JellyfinClient
from app.services.metadata import AudioTagContext, tag_audio_file
from app.services.webhooks import fire_sync_webhook
from app.version import get_app_version
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


class SyncEngine:
    def __init__(
        self,
        db_factory,
        registry: PlatformRegistry,
        downloader: DownloadService,
        jellyfin_client: JellyfinClient,
    ) -> None:
        self.db_factory = db_factory
        self.registry = registry
        self.downloader = downloader
        self.jellyfin_client = jellyfin_client
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._running_user_ids: set[int] = set()

    def _lock_for(self, user_id: int) -> asyncio.Lock:
        if user_id not in self._user_locks:
            self._user_locks[user_id] = asyncio.Lock()
        return self._user_locks[user_id]

    @property
    def is_sync_running(self) -> bool:
        return len(self._running_user_ids) > 0

    def is_user_sync_running(self, user_id: int) -> bool:
        return user_id in self._running_user_ids

    async def run_all_users_sync(self) -> None:
        db: Session = self.db_factory()
        try:
            users = db.scalars(select(User)).all()
            log.info("Scheduled sync started for %s user(s)", len(users))
            for user in users:
                await self._run_user_sync_locked(user.id)
            log.info("Scheduled sync finished for all users")
        finally:
            db.close()

    async def run_user_sync_by_id(self, user_id: int) -> None:
        await self._run_user_sync_locked(user_id)

    async def _run_user_sync_locked(self, user_id: int) -> None:
        lock = self._lock_for(user_id)
        async with lock:
            self._running_user_ids.add(user_id)
            db: Session = self.db_factory()
            try:
                await self.run_user_sync(db, user_id)
            finally:
                self._running_user_ids.discard(user_id)
                db.close()

    async def run_user_sync(self, db: Session, user_id: int) -> None:
        log.info("Sync started user_id=%s", user_id)
        links = db.scalars(select(PlatformLink).where(PlatformLink.user_id == user_id)).all()
        playlist_track_paths: dict[int, list[str | None]] = {}
        user = db.scalar(select(User).where(User.id == user_id))
        if not user:
            log.warning("Sync skipped: no user for user_id=%s", user_id)
            return

        db.execute(
            delete(DownloadTask).where(
                DownloadTask.user_id == user_id,
                DownloadTask.status.in_([DownloadStatus.PENDING.value, DownloadStatus.DOWNLOADING.value]),
            )
        )

        # Deduplicated download queue: one entry per unique source_id.
        # Each source_id maps to all playlist slots that need it.
        download_queue: list[tuple[DownloadRequest, int]] = []  # (req, task_id)
        source_id_to_idx: dict[str, int] = {}
        source_id_slots: dict[str, list[tuple[int, int]]] = {}  # source_id -> [(playlist_id, pos)]

        for link in links:
            connector = self.registry.get(link.platform)
            credentials = {}
            if link.credentials_json:
                credentials = json.loads(link.credentials_json)
            if link.platform == "spotify":
                credentials = await connector.refresh_credentials(
                    credentials=credentials,
                    client_id=get_effective_setting(db, "spotify_client_id"),
                    client_secret=get_effective_setting(db, "spotify_client_secret"),
                )
            if link.platform == "youtube":
                credentials = await connector.refresh_credentials(
                    credentials=credentials,
                    client_id=get_effective_setting(db, "google_client_id"),
                    client_secret=get_effective_setting(db, "google_client_secret"),
                )
            link.credentials_json = json.dumps(credentials)
            playlists = await connector.fetch_playlists(credentials)
            log.info("Platform %s: fetched %s playlist(s)", link.platform, len(playlists))
            for playlist in playlists:
                synced = db.scalar(
                    select(SyncedPlaylist).where(
                        SyncedPlaylist.user_id == user_id,
                        SyncedPlaylist.platform == link.platform,
                        SyncedPlaylist.platform_playlist_id == playlist.playlist_id,
                    )
                )
                if not synced:
                    synced = SyncedPlaylist(
                        user_id=user_id,
                        platform=link.platform,
                        platform_playlist_id=playlist.playlist_id,
                        platform_playlist_name=playlist.name,
                        enabled=True,
                    )
                    db.add(synced)
                    db.flush()
                if not synced.enabled:
                    continue
                playlist_track_paths[synced.id] = [None] * len(playlist.tracks)
                db.execute(delete(SyncedPlaylistTrack).where(SyncedPlaylistTrack.synced_playlist_id == synced.id))

                for pos, track in enumerate(playlist.tracks):
                    canonical = track
                    if link.platform == "spotify":
                        query = f"{track.title} {track.artist}"
                        youtube_match = await self.registry.get("youtube").search_track(query)
                        if youtube_match:
                            canonical = youtube_match
                            canonical.title = track.title
                            canonical.artist = track.artist
                            canonical.album = track.album

                    existing = db.scalar(select(Track).where(Track.source_id == canonical.source_id))
                    if existing:
                        playlist_track_paths[synced.id][pos] = existing.file_path
                        db.add(
                            SyncedPlaylistTrack(
                                synced_playlist_id=synced.id,
                                track_id=existing.id,
                                position=pos,
                            )
                        )
                        continue

                    disk_path = self.downloader.first_existing_audio_path(
                        track.title, track.artist, track.album, canonical.source_id
                    )
                    if disk_path is not None and disk_path.is_file():
                        path_keys = DownloadService.path_key_variants(disk_path)
                        by_path = db.scalar(select(Track).where(Track.file_path.in_(path_keys)))
                        if by_path is not None:
                            if by_path.source_id == canonical.source_id:
                                playlist_track_paths[synced.id][pos] = by_path.file_path
                                db.add(
                                    SyncedPlaylistTrack(
                                        synced_playlist_id=synced.id,
                                        track_id=by_path.id,
                                        position=pos,
                                    )
                                )
                                log.info("Linked track on disk (DB path match): %s — %s", track.artist, track.title)
                                continue
                            log.warning(
                                "File %s exists but is tied to source_id=%s (expected %s); will try normal download",
                                disk_path,
                                by_path.source_id,
                                canonical.source_id,
                            )
                        else:
                            file_path_str = str(disk_path.resolve())
                            track_row = Track(
                                title=track.title,
                                artist=track.artist,
                                album=track.album,
                                duration_seconds=0,
                                file_path=file_path_str,
                                source_platform="youtube",
                                source_id=canonical.source_id,
                                file_size=disk_path.stat().st_size,
                            )
                            try:
                                with db.begin_nested():
                                    db.add(track_row)
                                    db.flush()
                            except IntegrityError:
                                log.warning(
                                    "Disk import skipped (DB conflict for path=%s, source_id=%s); queuing download",
                                    file_path_str,
                                    canonical.source_id,
                                )
                            else:
                                tag_audio_file(
                                    disk_path,
                                    AudioTagContext(
                                        title=track.title,
                                        artist=track.artist,
                                        album=track.album,
                                        insync_version=get_app_version(),
                                    ),
                                )
                                playlist_track_paths[synced.id][pos] = track_row.file_path
                                db.add(
                                    SyncedPlaylistTrack(
                                        synced_playlist_id=synced.id,
                                        track_id=track_row.id,
                                        position=pos,
                                    )
                                )
                                log.info(
                                    "Imported file from disk into DB (skipped download): %s — %s",
                                    track.artist,
                                    track.title,
                                )
                                continue

                    # Deduplicate: if this source_id is already queued, just
                    # record the extra playlist slot instead of downloading again.
                    if canonical.source_id in source_id_to_idx:
                        source_id_slots[canonical.source_id].append((synced.id, pos))
                        log.debug(
                            "Dedup: source_id=%s already queued, adding slot playlist=%s pos=%s",
                            canonical.source_id,
                            synced.id,
                            pos,
                        )
                        continue

                    task = DownloadTask(
                        user_id=user_id,
                        source_id=canonical.source_id,
                        search_query=f"{track.title} {track.artist}",
                        title=track.title,
                        artist=track.artist,
                        status=DownloadStatus.PENDING.value,
                    )
                    db.add(task)
                    db.flush()

                    idx = len(download_queue)
                    source_id_to_idx[canonical.source_id] = idx
                    source_id_slots.setdefault(canonical.source_id, []).append((synced.id, pos))
                    download_queue.append(
                        (
                            DownloadRequest(
                                source_id=canonical.source_id,
                                search_query=f"{track.title} {track.artist}",
                                title=track.title,
                                artist=track.artist,
                                album=track.album,
                            ),
                            task.id,
                        )
                    )
                synced.last_synced = datetime.now(UTC)

        db.commit()

        already_in_library = sum(1 for paths in playlist_track_paths.values() for p in paths if p is not None)
        log.info(
            "Sync user_id=%s: playlist phase done; %s unique download(s) queued, %s track slot(s) already in library",
            user_id,
            len(download_queue),
            already_in_library,
        )

        if download_queue:
            any_success = False
            total_downloads = len(download_queue)
            finished_count = 0

            async def on_each_download_result(idx: int, result: DownloadResult) -> None:
                nonlocal any_success, finished_count
                req, task_id = download_queue[idx]
                slots = source_id_slots.get(req.source_id, [])
                finished_count += 1
                if result.error:
                    self._mark_task_terminal(task_id, DownloadStatus.FAILED.value, result.error)
                    log.warning(
                        "Download %s/%s failed task_id=%s: %s — %s | %s",
                        finished_count,
                        total_downloads,
                        task_id,
                        req.artist,
                        req.title,
                        result.error[:200] + ("…" if len(result.error) > 200 else ""),
                    )
                    return
                if result.path is None:
                    self._mark_task_terminal(task_id, DownloadStatus.FAILED.value, "No output file produced")
                    log.warning(
                        "Download %s/%s failed task_id=%s: %s — %s (no output file)",
                        finished_count,
                        total_downloads,
                        task_id,
                        req.artist,
                        req.title,
                    )
                    return
                path = result.path
                self._mark_task_terminal(task_id, DownloadStatus.COMPLETED.value, None)
                if not self._persist_downloaded_track(slots, req, path, playlist_track_paths):
                    self._mark_task_terminal(
                        task_id,
                        DownloadStatus.FAILED.value,
                        "Could not save track (database conflict)",
                    )
                    log.warning(
                        "Download %s/%s persist failed task_id=%s: %s — %s",
                        finished_count,
                        total_downloads,
                        task_id,
                        req.artist,
                        req.title,
                    )
                    return
                any_success = True
                log.info(
                    "Download %s/%s ok task_id=%s: %s — %s (%s playlist slot(s))",
                    finished_count,
                    total_downloads,
                    task_id,
                    req.artist,
                    req.title,
                    len(slots),
                )

            await self.downloader.download_many(
                [(req, task_id) for req, task_id in download_queue],
                on_downloading=self._mark_task_downloading,
                on_each_result=on_each_download_result,
            )

            if any_success:
                log.info("Refreshing Jellyfin library after new downloads (user_id=%s)", user_id)
                await self.jellyfin_client.refresh_library()
        else:
            log.info("Sync user_id=%s: no new downloads queued", user_id)

        all_synced = db.scalars(select(SyncedPlaylist).where(SyncedPlaylist.user_id == user_id)).all()
        log.info("Pushing %s synced playlist(s) to Jellyfin for user_id=%s", len(all_synced), user_id)
        for playlist in all_synced:
            raw_paths = playlist_track_paths.get(playlist.id, [])
            ordered_paths = [p for p in raw_paths if p is not None]
            item_ids = await self.jellyfin_client.resolve_item_ids_by_paths(
                user.jellyfin_user_id,
                ordered_paths,
            )
            log.info(
                "Playlist '%s' (id=%s): %s ordered paths -> %s resolved Jellyfin item IDs",
                playlist.platform_playlist_name,
                playlist.id,
                len(ordered_paths),
                len(item_ids),
            )
            if ordered_paths and not item_ids:
                log.warning(
                    "Playlist '%s': all paths unresolved — check that container mount paths match "
                    "between InSync and Jellyfin",
                    playlist.platform_playlist_name,
                )
            playlist_id = await self.jellyfin_client.create_or_update_playlist(
                user_id=user.jellyfin_user_id,
                playlist_name=playlist.platform_playlist_name,
                item_ids=item_ids,
                playlist_id=playlist.jellyfin_playlist_id,
            )
            if playlist_id:
                playlist.jellyfin_playlist_id = playlist_id
        db.commit()
        log.info("Sync finished user_id=%s", user_id)

        # Webhook notification
        filled = sum(1 for paths in playlist_track_paths.values() for p in paths if p is not None)
        total_downloaded = filled - already_in_library
        total_failed = (len(download_queue) - max(total_downloaded, 0)) if download_queue else 0
        event = "sync_failed" if total_failed > 0 and total_downloaded == 0 else "sync_complete"
        await fire_sync_webhook(
            self.db_factory,
            user_id=user_id,
            username=user.jellyfin_username,
            event=event,
            playlists_synced=len(all_synced),
            tracks_downloaded=max(total_downloaded, 0),
            failures=max(total_failed, 0),
        )

    async def run_single_playlist_sync(self, user_id: int, synced_playlist_id: int) -> None:
        """Sync only a single playlist for a user (fetch + download + Jellyfin push)."""
        lock = self._lock_for(user_id)
        async with lock:
            self._running_user_ids.add(user_id)
            db: Session = self.db_factory()
            try:
                await self._sync_single_playlist(db, user_id, synced_playlist_id)
            finally:
                self._running_user_ids.discard(user_id)
                db.close()

    async def _sync_single_playlist(self, db: Session, user_id: int, synced_playlist_id: int) -> None:
        user = db.scalar(select(User).where(User.id == user_id))
        if not user:
            return
        synced = db.scalar(
            select(SyncedPlaylist).where(SyncedPlaylist.id == synced_playlist_id, SyncedPlaylist.user_id == user_id)
        )
        if not synced:
            log.warning("Single-playlist sync: playlist %s not found for user %s", synced_playlist_id, user_id)
            return
        link = db.scalar(
            select(PlatformLink).where(PlatformLink.user_id == user_id, PlatformLink.platform == synced.platform)
        )
        if not link:
            log.warning("Single-playlist sync: no platform link for %s", synced.platform)
            return

        connector = self.registry.get(link.platform)
        credentials = json.loads(link.credentials_json) if link.credentials_json else {}
        if link.platform == "spotify":
            credentials = await connector.refresh_credentials(
                credentials=credentials,
                client_id=get_effective_setting(db, "spotify_client_id"),
                client_secret=get_effective_setting(db, "spotify_client_secret"),
            )
        if link.platform == "youtube":
            credentials = await connector.refresh_credentials(
                credentials=credentials,
                client_id=get_effective_setting(db, "google_client_id"),
                client_secret=get_effective_setting(db, "google_client_secret"),
            )
        link.credentials_json = json.dumps(credentials)

        all_playlists = await connector.fetch_playlists(credentials)
        target = next(
            (p for p in all_playlists if p.playlist_id == synced.platform_playlist_id),
            None,
        )
        if not target:
            log.warning("Single-playlist sync: upstream playlist %s not found", synced.platform_playlist_id)
            return

        playlist_track_paths: dict[int, list[str | None]] = {synced.id: [None] * len(target.tracks)}
        db.execute(delete(SyncedPlaylistTrack).where(SyncedPlaylistTrack.synced_playlist_id == synced.id))

        download_queue: list[tuple[DownloadRequest, int]] = []
        source_id_to_idx: dict[str, int] = {}
        source_id_slots: dict[str, list[tuple[int, int]]] = {}

        for pos, track in enumerate(target.tracks):
            canonical = track
            if link.platform == "spotify":
                query = f"{track.title} {track.artist}"
                youtube_match = await self.registry.get("youtube").search_track(query)
                if youtube_match:
                    canonical = youtube_match
                    canonical.title = track.title
                    canonical.artist = track.artist
                    canonical.album = track.album

            existing = db.scalar(select(Track).where(Track.source_id == canonical.source_id))
            if existing:
                playlist_track_paths[synced.id][pos] = existing.file_path
                db.add(SyncedPlaylistTrack(synced_playlist_id=synced.id, track_id=existing.id, position=pos))
                continue

            if canonical.source_id in source_id_to_idx:
                source_id_slots[canonical.source_id].append((synced.id, pos))
                continue

            task = DownloadTask(
                user_id=user_id,
                source_id=canonical.source_id,
                search_query=f"{track.title} {track.artist}",
                title=track.title,
                artist=track.artist,
                status=DownloadStatus.PENDING.value,
            )
            db.add(task)
            db.flush()

            idx = len(download_queue)
            source_id_to_idx[canonical.source_id] = idx
            source_id_slots.setdefault(canonical.source_id, []).append((synced.id, pos))
            download_queue.append(
                (
                    DownloadRequest(
                        source_id=canonical.source_id,
                        search_query=f"{track.title} {track.artist}",
                        title=track.title,
                        artist=track.artist,
                        album=track.album,
                    ),
                    task.id,
                )
            )

        synced.last_synced = datetime.now(UTC)
        db.commit()

        if download_queue:
            any_success = False

            async def on_result(idx: int, result: DownloadResult) -> None:
                nonlocal any_success
                req, task_id = download_queue[idx]
                slots = source_id_slots.get(req.source_id, [])
                if result.error or result.path is None:
                    self._mark_task_terminal(task_id, DownloadStatus.FAILED.value, result.error or "No file")
                    return
                self._mark_task_terminal(task_id, DownloadStatus.COMPLETED.value, None)
                if self._persist_downloaded_track(slots, req, result.path, playlist_track_paths):
                    any_success = True

            await self.downloader.download_many(
                [(req, tid) for req, tid in download_queue],
                on_downloading=self._mark_task_downloading,
                on_each_result=on_result,
            )
            if any_success:
                await self.jellyfin_client.refresh_library()

        raw_paths = playlist_track_paths.get(synced.id, [])
        ordered = [p for p in raw_paths if p is not None]
        item_ids = await self.jellyfin_client.resolve_item_ids_by_paths(user.jellyfin_user_id, ordered)
        log.info(
            "Single-playlist '%s' (id=%s): %s ordered paths -> %s resolved Jellyfin item IDs",
            synced.platform_playlist_name,
            synced.id,
            len(ordered),
            len(item_ids),
        )
        if ordered and not item_ids:
            log.warning(
                "Single-playlist '%s': all paths unresolved — check that container mount paths match "
                "between InSync and Jellyfin",
                synced.platform_playlist_name,
            )
        jf_id = await self.jellyfin_client.create_or_update_playlist(
            user_id=user.jellyfin_user_id,
            playlist_name=synced.platform_playlist_name,
            item_ids=item_ids,
            playlist_id=synced.jellyfin_playlist_id,
        )
        if jf_id:
            synced.jellyfin_playlist_id = jf_id
        db.commit()
        log.info("Single-playlist sync finished: playlist_id=%s user_id=%s", synced_playlist_id, user_id)

    def _persist_downloaded_track(
        self,
        slots: list[tuple[int, int]],
        req: DownloadRequest,
        path: Path,
        playlist_track_paths: dict[int, list[str | None]],
    ) -> bool:
        """Insert the Track row and link it to every playlist slot.

        If the Track already exists (IntegrityError on source_id or file_path),
        look it up and create the playlist links anyway.
        """
        s: Session = self.db_factory()
        try:
            track_id: int | None = None
            file_path_str = str(path)

            try:
                track = Track(
                    title=req.title,
                    artist=req.artist,
                    album=req.album,
                    duration_seconds=0,
                    file_path=file_path_str,
                    source_platform="youtube",
                    source_id=req.source_id,
                    file_size=path.stat().st_size if path.exists() else 0,
                )
                s.add(track)
                s.flush()
                track_id = track.id
            except IntegrityError:
                s.rollback()
                existing = s.scalar(select(Track).where(Track.source_id == req.source_id))
                if existing:
                    track_id = existing.id
                    file_path_str = existing.file_path
                    log.info(
                        "Track already exists for source_id=%s, reusing track_id=%s",
                        req.source_id,
                        track_id,
                    )
                else:
                    log.warning(
                        "Track insert conflict for %s — %s (source_id=%s) and no existing row found",
                        req.artist,
                        req.title,
                        req.source_id,
                    )
                    return False

            for playlist_id, pos in slots:
                playlist_track_paths[playlist_id][pos] = file_path_str
                s.add(
                    SyncedPlaylistTrack(
                        synced_playlist_id=playlist_id,
                        track_id=track_id,
                        position=pos,
                    )
                )
            s.commit()
            return True
        except Exception:
            s.rollback()
            log.exception(
                "Unexpected error persisting track %s — %s (source_id=%s)",
                req.artist,
                req.title,
                req.source_id,
            )
            return False
        finally:
            s.close()

    def _mark_task_downloading(self, task_id: int) -> None:
        s: Session = self.db_factory()
        try:
            task = s.get(DownloadTask, task_id)
            if task:
                task.status = DownloadStatus.DOWNLOADING.value
                s.commit()
        finally:
            s.close()

    def _mark_task_terminal(self, task_id: int, status: str, error_message: str | None) -> None:
        s: Session = self.db_factory()
        try:
            task = s.get(DownloadTask, task_id)
            if task:
                task.status = status
                task.error_message = error_message
                task.completed_at = datetime.now(UTC)
                s.commit()
        finally:
            s.close()
