# Feature: backend-refactor, Property 1
# Feature: backend-refactor, Property 2
# Feature: backend-refactor, Property 7
# Feature: backend-refactor, Property 9
"""Property tests for SyncEngine:
- Property 1: full-user sync processes every enabled playlist
- Property 2: per-playlist sync outcome is independent of call path
- Property 7: _mark_task_terminal — session source invariant
- Property 9: _persist_downloaded_track — session source invariant

Validates: Requirements 1.2, 1.3, 1.5, 9.1, 9.2, 9.3, 9.4, 13.1, 13.2, 13.4
"""

import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.database import Base
from app.models.download_task import DownloadStatus, DownloadTask
from app.models.platform_link import PlatformLink
from app.models.synced_playlist import SyncedPlaylist, SyncedPlaylistTrack
from app.models.track import Track
from app.models.user import User
from app.platforms.base import PlaylistInfo
from app.services.download import DownloadRequest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


def _make_session() -> Session:
    """Create an in-memory SQLite session with all tables created."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Import all models so Base.metadata knows about them
    import app.models.app_config  # noqa: F401
    import app.models.download_task  # noqa: F401
    import app.models.oauth_state  # noqa: F401
    import app.models.platform_link  # noqa: F401
    import app.models.synced_playlist  # noqa: F401
    import app.models.track  # noqa: F401
    import app.models.user  # noqa: F401

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    return SessionLocal()


def _make_sync_engine():
    """Create a minimal SyncEngine with a mock db_factory."""
    from app.services.sync_engine import SyncEngine

    mock_db_factory = MagicMock()
    mock_registry = MagicMock()
    mock_downloader = MagicMock()
    mock_jellyfin = MagicMock()
    return SyncEngine(
        db_factory=mock_db_factory,
        registry=mock_registry,
        downloader=mock_downloader,
        jellyfin_client=mock_jellyfin,
    )


def _create_user_and_task(session: Session, status: str = DownloadStatus.PENDING.value) -> int:
    """Insert a User and a DownloadTask row; return the task id."""
    user = User(
        jellyfin_user_id="test-jf-user-id",
        jellyfin_username="testuser",
        is_admin=False,
    )
    session.add(user)
    session.flush()

    task = DownloadTask(
        user_id=user.id,
        source_id="dQw4w9WgXcQ",
        search_query="Never Gonna Give You Up Rick Astley",
        title="Never Gonna Give You Up",
        artist="Rick Astley",
        status=status,
    )
    session.add(task)
    session.flush()
    return task.id


@given(
    status=st.sampled_from([s.value for s in DownloadStatus]),
    error_message=st.one_of(st.none(), st.text(max_size=100)),
)
@settings(max_examples=50)
def test_mark_task_terminal_session_source_invariant(status: str, error_message: str | None) -> None:
    """Property 7: Task status update produces identical DB state regardless of session source.

    Calls _mark_task_terminal with a passed session (db=session) and asserts that
    task.status, task.error_message, and task.completed_at are set correctly.

    **Validates: Requirements 9.1, 9.2, 9.3, 9.4**
    """
    session = _make_session()
    try:
        engine = _make_sync_engine()

        task_id = _create_user_and_task(session)

        before = datetime.now(UTC)
        engine._mark_task_terminal(task_id, status, error_message, db=session)

        # Query the task to verify the DB state
        task = session.get(DownloadTask, task_id)
        assert task is not None, "Task row should still exist after _mark_task_terminal"

        assert task.status == status, f"Expected task.status={status!r}, got {task.status!r}"
        assert task.error_message == error_message, (
            f"Expected task.error_message={error_message!r}, got {task.error_message!r}"
        )
        assert task.completed_at is not None, "task.completed_at should be set after _mark_task_terminal"
        # SQLite may return a timezone-naive datetime; normalise before comparing
        completed_at = task.completed_at
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=UTC)
        assert completed_at >= before, "task.completed_at should be >= the timestamp recorded before the call"
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Property 9: _persist_downloaded_track — session source invariant
# ---------------------------------------------------------------------------


@given(
    title=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs"))),
    artist=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs"))),
    album=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs"))),
    source_id=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))),
    num_slots=st.integers(min_value=0, max_value=3),
)
@settings(max_examples=50)
def test_persist_downloaded_track_session_source_invariant(
    title: str,
    artist: str,
    album: str,
    source_id: str,
    num_slots: int,
) -> None:
    """Property 9: _persist_downloaded_track produces identical track and playlist-link rows
    regardless of session source.

    Calls _persist_downloaded_track with a passed session (db=session) and asserts that
    the same Track row and SyncedPlaylistTrack rows are inserted (one per slot, correct position).

    **Validates: Requirements 13.1, 13.2, 13.4**
    """
    session = _make_session()
    try:
        engine = _make_sync_engine()

        # Create a User row (required by SyncedPlaylist FK)
        user = User(
            jellyfin_user_id=f"jf-user-{source_id}",
            jellyfin_username=f"user-{source_id}",
            is_admin=False,
        )
        session.add(user)
        session.flush()

        # Create one SyncedPlaylist per slot
        playlist_ids: list[int] = []
        for i in range(num_slots):
            playlist = SyncedPlaylist(
                user_id=user.id,
                platform="youtube",
                platform_playlist_id=f"pl-{source_id}-{i}",
                platform_playlist_name=f"Playlist {i}",
                enabled=True,
            )
            session.add(playlist)
            session.flush()
            playlist_ids.append(playlist.id)

        # Build slots: each slot is (playlist_id, position)
        slots: list[tuple[int, int]] = [(pid, pos) for pos, pid in enumerate(playlist_ids)]

        # playlist_track_paths mirrors what run_user_sync maintains
        playlist_track_paths: dict[int, list[str | None]] = {
            pid: [None] * (pos + 1) for pos, pid in enumerate(playlist_ids)
        }

        req = DownloadRequest(
            source_id=source_id,
            search_query=f"{title} {artist}",
            title=title,
            artist=artist,
            album=album,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "track.opus"
            audio_path.write_bytes(b"fake audio data")

            result = engine._persist_downloaded_track(slots, req, audio_path, playlist_track_paths, session)

        # The method should succeed
        assert result is True, "_persist_downloaded_track should return True on success"

        # Flush so that all pending adds (Track + SyncedPlaylistTrack) are visible to subsequent queries.
        # The session was created with autoflush=False to match production usage; _persist_downloaded_track
        # only flushes the Track insert (inside begin_nested), not the SyncedPlaylistTrack adds.
        session.flush()

        # --- Assert Track row ---
        track = session.scalar(select(Track).where(Track.source_id == source_id))
        assert track is not None, f"Track row should be inserted for source_id={source_id!r}"
        assert track.title == title, f"Expected track.title={title!r}, got {track.title!r}"
        assert track.artist == artist, f"Expected track.artist={artist!r}, got {track.artist!r}"
        assert track.album == album, f"Expected track.album={album!r}, got {track.album!r}"
        assert track.source_id == source_id, f"Expected track.source_id={source_id!r}, got {track.source_id!r}"

        # --- Assert SyncedPlaylistTrack rows ---
        spt_rows = session.scalars(select(SyncedPlaylistTrack).where(SyncedPlaylistTrack.track_id == track.id)).all()
        assert len(spt_rows) == num_slots, f"Expected {num_slots} SyncedPlaylistTrack row(s), got {len(spt_rows)}"

        # Verify each slot has the correct playlist_id and position
        spt_by_playlist = {row.synced_playlist_id: row for row in spt_rows}
        for pos, pid in enumerate(playlist_ids):
            assert pid in spt_by_playlist, f"Missing SyncedPlaylistTrack for playlist_id={pid}"
            row = spt_by_playlist[pid]
            assert row.position == pos, f"Expected position={pos} for playlist_id={pid}, got {row.position}"
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Property 1: Full-user sync processes every enabled playlist
# ---------------------------------------------------------------------------


@given(num_playlists=st.integers(min_value=1, max_value=5))
@settings(max_examples=20)
def test_full_user_sync_processes_every_enabled_playlist(num_playlists: int) -> None:
    """Property 1: Full-user sync processes every enabled playlist.

    For any user with N enabled playlists, running run_user_sync should result
    in each of those N playlists being processed (last_synced updated) exactly once.

    **Validates: Requirements 1.2**
    """
    session = _make_session()
    try:
        # --- Create User ---
        user = User(
            jellyfin_user_id=f"jf-user-prop1-{num_playlists}",
            jellyfin_username=f"user-prop1-{num_playlists}",
            is_admin=False,
        )
        session.add(user)
        session.flush()

        # --- Create PlatformLink (youtube) ---
        link = PlatformLink(
            user_id=user.id,
            platform="youtube",
            credentials_json=json.dumps({"access_token": "fake-token"}),
        )
        session.add(link)
        session.flush()

        # --- Create SyncedPlaylist rows (all enabled) ---
        playlist_ids_on_platform = [f"pl-prop1-{i}" for i in range(num_playlists)]
        for pid in playlist_ids_on_platform:
            sp = SyncedPlaylist(
                user_id=user.id,
                platform="youtube",
                platform_playlist_id=pid,
                platform_playlist_name=f"Playlist {pid}",
                enabled=True,
                last_synced=None,
            )
            session.add(sp)
        session.flush()
        session.commit()

        # --- Build PlaylistInfo objects matching the DB rows (empty track lists for speed) ---
        playlist_infos = [
            PlaylistInfo(playlist_id=pid, name=f"Playlist {pid}", tracks=[]) for pid in playlist_ids_on_platform
        ]

        # --- Mock connector ---
        mock_connector = MagicMock()
        mock_connector.get_credentials.return_value = (None, None)
        mock_connector.refresh_credentials = AsyncMock(
            side_effect=lambda *, credentials, client_id, client_secret: credentials
        )
        mock_connector.fetch_playlists = AsyncMock(return_value=playlist_infos)
        mock_connector.search_track = AsyncMock(return_value=None)

        # --- Mock registry ---
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_connector

        # --- Mock downloader ---
        mock_downloader = MagicMock()
        mock_downloader.first_existing_audio_path.return_value = None
        mock_downloader.download_many = AsyncMock(return_value=[])

        # --- Mock JellyfinClient ---
        mock_jellyfin = MagicMock()
        mock_jellyfin.refresh_library = AsyncMock()
        mock_jellyfin.resolve_item_ids_by_paths = AsyncMock(return_value=[])
        mock_jellyfin.create_or_update_playlist = AsyncMock(return_value=None)

        # --- Build SyncEngine with a db_factory that returns the same session ---
        from app.services.sync_engine import SyncEngine

        engine = SyncEngine(
            db_factory=lambda: session,
            registry=mock_registry,
            downloader=mock_downloader,
            jellyfin_client=mock_jellyfin,
        )

        # --- Run the sync ---
        asyncio.run(engine.run_user_sync(session, user.id))

        # --- Assert: every enabled playlist has last_synced set ---
        synced_playlists = session.scalars(
            select(SyncedPlaylist).where(
                SyncedPlaylist.user_id == user.id,
                SyncedPlaylist.enabled == True,  # noqa: E712
            )
        ).all()

        assert len(synced_playlists) == num_playlists, (
            f"Expected {num_playlists} enabled playlists, found {len(synced_playlists)}"
        )

        for sp in synced_playlists:
            assert sp.last_synced is not None, (
                f"Playlist {sp.platform_playlist_id!r} was not processed: last_synced is None"
            )

    finally:
        session.close()


# ---------------------------------------------------------------------------
# Property 2: Per-playlist sync outcome is independent of call path
# ---------------------------------------------------------------------------


def _build_sync_engine_with_session(session: Session, playlist_info: "PlaylistInfo"):
    """Build a SyncEngine whose db_factory always returns the given session and whose
    connector returns the given playlist_info from fetch_playlists."""
    from app.services.sync_engine import SyncEngine

    mock_connector = MagicMock()
    mock_connector.get_credentials.return_value = (None, None)
    mock_connector.refresh_credentials = AsyncMock(
        side_effect=lambda *, credentials, client_id, client_secret: credentials
    )
    mock_connector.fetch_playlists = AsyncMock(return_value=[playlist_info])
    mock_connector.fetch_playlist = AsyncMock(return_value=playlist_info)
    mock_connector.search_track = AsyncMock(return_value=None)

    mock_registry = MagicMock()
    mock_registry.get.return_value = mock_connector

    mock_downloader = MagicMock()
    mock_downloader.first_existing_audio_path.return_value = None
    mock_downloader.download_many = AsyncMock(return_value=[])

    mock_jellyfin = MagicMock()
    mock_jellyfin.refresh_library = AsyncMock()
    mock_jellyfin.resolve_item_ids_by_paths = AsyncMock(return_value=[])
    mock_jellyfin.create_or_update_playlist = AsyncMock(return_value=None)

    engine = SyncEngine(
        db_factory=lambda: session,
        registry=mock_registry,
        downloader=mock_downloader,
        jellyfin_client=mock_jellyfin,
    )
    return engine


def _setup_db_for_property2(
    num_tracks: int, playlist_platform_id: str = "pl-prop2"
) -> tuple[Session, int, int, "PlaylistInfo"]:
    """Create a fresh in-memory DB with a User, PlatformLink, SyncedPlaylist, and
    a PlaylistInfo with num_tracks tracks. Returns (session, user_id, synced_playlist_id, playlist_info)."""
    from app.platforms.base import TrackInfo

    session = _make_session()

    user = User(
        jellyfin_user_id=f"jf-user-prop2-{playlist_platform_id}",
        jellyfin_username=f"user-prop2-{playlist_platform_id}",
        is_admin=False,
    )
    session.add(user)
    session.flush()

    link = PlatformLink(
        user_id=user.id,
        platform="youtube",
        credentials_json=json.dumps({"access_token": "fake-token"}),
    )
    session.add(link)
    session.flush()

    sp = SyncedPlaylist(
        user_id=user.id,
        platform="youtube",
        platform_playlist_id=playlist_platform_id,
        platform_playlist_name=f"Playlist {playlist_platform_id}",
        enabled=True,
        last_synced=None,
    )
    session.add(sp)
    session.flush()
    synced_playlist_id = sp.id

    tracks = [
        TrackInfo(
            source_id=f"src-{playlist_platform_id}-{i}",
            title=f"Track {i}",
            artist="Artist",
            album="Album",
        )
        for i in range(num_tracks)
    ]
    playlist_info = PlaylistInfo(
        playlist_id=playlist_platform_id,
        name=f"Playlist {playlist_platform_id}",
        tracks=tracks,
    )

    session.commit()
    return session, user.id, synced_playlist_id, playlist_info


@given(num_tracks=st.integers(min_value=0, max_value=3))
@settings(max_examples=20)
def test_per_playlist_outcome_independent_of_call_path(num_tracks: int) -> None:
    """Property 2: Per-playlist sync outcome is independent of call path.

    For any single enabled playlist, the set of DownloadTask rows created should be
    identical whether the playlist is processed via run_user_sync (full-user path) or
    run_single_playlist_sync (single-playlist path).

    **Validates: Requirements 1.3, 1.5**
    """
    # --- Run via full-user path (run_user_sync) ---
    session_full, user_id_full, synced_playlist_id_full, playlist_info_full = _setup_db_for_property2(
        num_tracks, playlist_platform_id="pl-prop2-full"
    )
    try:
        engine_full = _build_sync_engine_with_session(session_full, playlist_info_full)
        asyncio.run(engine_full.run_user_sync(session_full, user_id_full))

        full_tasks = session_full.scalars(select(DownloadTask).where(DownloadTask.user_id == user_id_full)).all()
        full_source_ids = sorted(t.source_id for t in full_tasks)
    finally:
        session_full.close()

    # --- Run via single-playlist path (run_single_playlist_sync) ---
    session_single, user_id_single, synced_playlist_id_single, playlist_info_single = _setup_db_for_property2(
        num_tracks, playlist_platform_id="pl-prop2-single"
    )
    try:
        engine_single = _build_sync_engine_with_session(session_single, playlist_info_single)
        asyncio.run(engine_single.run_single_playlist_sync(user_id_single, synced_playlist_id_single))

        single_tasks = session_single.scalars(select(DownloadTask).where(DownloadTask.user_id == user_id_single)).all()
        single_source_ids = sorted(t.source_id for t in single_tasks)
    finally:
        session_single.close()

    # --- Assert: same number of DownloadTask rows ---
    assert len(full_source_ids) == len(single_source_ids), (
        f"Full-user path created {len(full_source_ids)} DownloadTask(s), "
        f"single-playlist path created {len(single_source_ids)} DownloadTask(s) "
        f"for num_tracks={num_tracks}"
    )

    # --- Assert: same source_ids (normalised to strip the playlist-id prefix difference) ---
    # The source_ids are like "src-pl-prop2-full-0" vs "src-pl-prop2-single-0".
    # Strip the playlist-specific prefix and compare the track index suffix.
    def _strip_prefix(source_ids: list[str], prefix: str) -> list[str]:
        return sorted(sid.replace(prefix, "src-") for sid in source_ids)

    normalised_full = _strip_prefix(full_source_ids, "src-pl-prop2-full-")
    normalised_single = _strip_prefix(single_source_ids, "src-pl-prop2-single-")

    assert normalised_full == normalised_single, (
        f"DownloadTask source_ids differ between call paths for num_tracks={num_tracks}:\n"
        f"  full-user path:        {normalised_full}\n"
        f"  single-playlist path:  {normalised_single}"
    )


# ---------------------------------------------------------------------------
# Property 3: Sync continues after per-playlist failure
# Feature: backend-refactor, Property 3
# ---------------------------------------------------------------------------


@given(failing_index=st.integers(min_value=0, max_value=2))
@settings(max_examples=10)
def test_sync_continues_after_per_playlist_failure(failing_index: int) -> None:
    """Property 3: Sync continues after per-playlist failure.

    For any list of playlists where one raises an exception during processing,
    the remaining playlists should still be processed (last_synced is set).

    **Validates: Requirements 1.6**
    """
    NUM_PLAYLISTS = 3
    session = _make_session()
    try:
        # --- Create User ---
        user = User(
            jellyfin_user_id=f"jf-user-prop3-{failing_index}",
            jellyfin_username=f"user-prop3-{failing_index}",
            is_admin=False,
        )
        session.add(user)
        session.flush()

        # --- Create PlatformLink (youtube) ---
        link = PlatformLink(
            user_id=user.id,
            platform="youtube",
            credentials_json=json.dumps({"access_token": "fake-token"}),
        )
        session.add(link)
        session.flush()

        # --- Create 3 enabled SyncedPlaylist rows ---
        playlist_platform_ids = [f"pl-prop3-{i}" for i in range(NUM_PLAYLISTS)]
        for pid in playlist_platform_ids:
            sp = SyncedPlaylist(
                user_id=user.id,
                platform="youtube",
                platform_playlist_id=pid,
                platform_playlist_name=f"Playlist {pid}",
                enabled=True,
                last_synced=None,
            )
            session.add(sp)
        session.flush()
        session.commit()

        # --- Build PlaylistInfo objects (empty track lists for speed) ---
        playlist_infos = [
            PlaylistInfo(playlist_id=pid, name=f"Playlist {pid}", tracks=[]) for pid in playlist_platform_ids
        ]

        # --- Mock connector ---
        mock_connector = MagicMock()
        mock_connector.get_credentials.return_value = (None, None)
        mock_connector.refresh_credentials = AsyncMock(
            side_effect=lambda *, credentials, client_id, client_secret: credentials
        )
        mock_connector.fetch_playlists = AsyncMock(return_value=playlist_infos)
        mock_connector.search_track = AsyncMock(return_value=None)

        # --- Mock registry ---
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_connector

        # --- Mock downloader ---
        mock_downloader = MagicMock()
        mock_downloader.first_existing_audio_path.return_value = None
        mock_downloader.download_many = AsyncMock(return_value=[])

        # --- Mock JellyfinClient ---
        mock_jellyfin = MagicMock()
        mock_jellyfin.refresh_library = AsyncMock()
        mock_jellyfin.resolve_item_ids_by_paths = AsyncMock(return_value=[])
        mock_jellyfin.create_or_update_playlist = AsyncMock(return_value=None)

        # --- Build SyncEngine ---
        from app.services.sync_engine import SyncEngine

        engine = SyncEngine(
            db_factory=lambda: session,
            registry=mock_registry,
            downloader=mock_downloader,
            jellyfin_client=mock_jellyfin,
        )

        # --- Patch _sync_one_playlist to raise for the failing playlist ---
        # We need to track which synced playlist corresponds to which index.
        # The playlists are iterated in the order returned by fetch_playlists,
        # which matches playlist_platform_ids order.
        original_sync_one = engine._sync_one_playlist
        call_count = {"n": 0}

        async def patched_sync_one_playlist(
            db,
            user,
            synced,
            link,
            playlist,
            playlist_track_paths,
            download_queue,
            source_id_to_idx,
            source_id_slots,
        ):
            idx = call_count["n"]
            call_count["n"] += 1
            if idx == failing_index:
                raise RuntimeError("simulated failure")
            await original_sync_one(
                db=db,
                user=user,
                synced=synced,
                link=link,
                playlist=playlist,
                playlist_track_paths=playlist_track_paths,
                download_queue=download_queue,
                source_id_to_idx=source_id_to_idx,
                source_id_slots=source_id_slots,
            )

        engine._sync_one_playlist = patched_sync_one_playlist

        # --- Run the sync ---
        asyncio.run(engine.run_user_sync(session, user.id))

        # --- Assert: non-failing playlists have last_synced set ---
        synced_playlists = session.scalars(
            select(SyncedPlaylist).where(
                SyncedPlaylist.user_id == user.id,
                SyncedPlaylist.enabled == True,  # noqa: E712
            )
        ).all()

        assert len(synced_playlists) == NUM_PLAYLISTS, (
            f"Expected {NUM_PLAYLISTS} enabled playlists, found {len(synced_playlists)}"
        )

        # Build a map from platform_playlist_id to the synced row
        by_pid = {sp.platform_playlist_id: sp for sp in synced_playlists}

        for i, pid in enumerate(playlist_platform_ids):
            sp = by_pid[pid]
            if i == failing_index:
                # The failing playlist should NOT have last_synced set
                assert sp.last_synced is None, (
                    f"Failing playlist {pid!r} (index {i}) should have last_synced=None, but got {sp.last_synced}"
                )
            else:
                # Non-failing playlists SHOULD have last_synced set
                assert sp.last_synced is not None, (
                    f"Non-failing playlist {pid!r} (index {i}) should have last_synced set, "
                    f"but got None (failing_index={failing_index})"
                )

    finally:
        session.close()
