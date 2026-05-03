# Implementation Plan: Backend Refactor

## Overview

Thirteen targeted deletions and small structural moves across eight files. Every task reduces line count; none adds new external behaviour. The test suite (`uv run pytest`) and Ruff lint (`uv run ruff check`) must stay green after each task.

Tasks follow the dependency order specified in the design: quick wins first, then foundational plumbing changes, then the larger sync-engine deduplication that depends on that plumbing, and finally additive work (response models, property tests).

---

## Tasks

- [x] 1. Quick wins — delete dead code and fix trivial style issues
  - [x] 1.1 Delete `_run_sync_in_background` from `app/api/sync.py`
    - Remove the function definition (~4 lines); verify no remaining references with a project-wide search
    - _Requirements: 7.1, 7.2, 7.3_

  - [x] 1.2 Move `import json` to module level in `app/services/webhooks.py`
    - Move the `import json` statement from inside the `if secret:` block to the top-level imports section
    - Run `uv run ruff check backend/app/services/webhooks.py` to confirm no import-order violations
    - _Requirements: 12.1, 12.2, 12.3_

  - [x] 1.3 Delete the duplicate `POST /api/sync/playlist/{id}` endpoint from `app/api/sync.py`
    - Remove the `sync_single_playlist` handler and its `@router.post("/playlist/{synced_playlist_id}")` decorator
    - Add a test in `tests/test_api.py` asserting that `POST /api/sync/playlist/1` returns HTTP 404
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 1.4 Delete legacy path methods from `app/services/download.py`
    - Remove `legacy_mp3_path`, `flat_legacy_mp3_path`, and `expected_mp3_path` methods
    - Inline their path construction directly into `first_existing_audio_path` so the candidate list is unchanged: `[unique_audio_path(...), music_dir / _safe_name(artist) / f"{_safe_name(title)}.mp3", music_dir / _safe_name(artist) / _safe_name(album) / f"{_safe_name(title)}.mp3"]`
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 1.5 Write property test for `first_existing_audio_path` path-priority ordering
    - **Property 6: `first_existing_audio_path` returns highest-priority existing path**
    - **Validates: Requirements 6.2, 6.3**
    - Use `hypothesis` with `tmp_path`-style temp dirs; vary which subset of the three candidate paths exist on disk and assert the returned path is always the highest-priority one that exists
    - Add `hypothesis` to `[dependency-groups] dev` in `pyproject.toml` if not already present; run `uv sync`
    - Tag: `# Feature: backend-refactor, Property 6`

- [x] 2. Checkpoint — ensure all tests pass after quick wins
  - Run `uv run pytest` and `uv run ruff check`; resolve any failures before continuing.

- [x] 3. Consolidate `AppConfig` upsert — replace inline copies with `set_setting()`
  - [x] 3.1 Replace inline upsert in `app/api/admin.py`
    - Import `set_setting` from `app.services.app_config`
    - Replace the `for key, value in changes.items(): row = db.scalar(...) if row: ... else: db.add(AppConfig(...))` loop body with `set_setting(db, key, str(value))`
    - Remove the now-unused `from app.models.app_config import AppConfig` import if it is no longer referenced in `admin.py`
    - _Requirements: 4.1, 4.4_

  - [x] 3.2 Replace inline upsert in `app/api/setup.py`
    - Import `set_setting` from `app.services.app_config`
    - Replace the `for key, value in {...}.items(): row = db.scalar(...) if row: ... else: db.add(AppConfig(...))` block with two direct `set_setting(db, "jellyfin_url", ...)` and `set_setting(db, "jellyfin_api_key", ...)` calls
    - Remove the now-unused `from app.models.app_config import AppConfig` and `from sqlalchemy import select` imports if no longer needed
    - _Requirements: 4.2, 4.4_

  - [x] 3.3 Replace inline upserts in `app/state.py`
    - Import `set_setting` from `app.services.app_config`
    - In `seed_jellyfin_from_env_if_db_incomplete`: replace the four `if url_row: url_row.value = ... else: db.add(AppConfig(...))` branches with `set_setting(db, "jellyfin_url", url_value)` and `set_setting(db, "jellyfin_api_key", key_value)`
    - In `bootstrap_jwt_secret`: replace the `if row: row.value = ... else: db.add(AppConfig(...))` branch with `set_setting(db, "jwt_secret", effective_secret)`
    - Remove the now-unused `from app.models.app_config import AppConfig` import from `state.py` if no longer referenced
    - _Requirements: 4.3, 4.4, 4.5_

  - [x] 3.4 Write property test for `set_setting` idempotency
    - **Property 5: `set_setting` upsert is idempotent**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.5**
    - Use an in-memory SQLite session; vary key names and value strings; assert that after two calls with different values exactly one `AppConfig` row exists for the key and it holds the second value
    - Tag: `# Feature: backend-refactor, Property 5`

- [x] 4. Extract AppState startup methods as module-level functions
  - [x] 4.1 Move the four startup methods out of `AppState` in `app/state.py`
    - Convert `bootstrap_jwt_secret`, `seed_jellyfin_from_env_if_db_incomplete`, `hydrate_jellyfin_from_db`, and `hydrate_audio_config_from_db` from instance methods to module-level functions with the same signatures (replace `self` references with direct access to the `app_state` singleton where needed for `hydrate_*`)
    - `AppState.__init__` and the `scheduler` attribute remain; the class becomes a plain holder
    - _Requirements: 3.1, 3.3_

  - [x] 4.2 Update `app/main.py` lifespan to call the module-level functions
    - Replace `app_state.bootstrap_jwt_secret(db)`, `app_state.seed_jellyfin_from_env_if_db_incomplete(db)`, `app_state.hydrate_jellyfin_from_db(db)`, `app_state.hydrate_audio_config_from_db(db)` with the new module-level calls, preserving the existing call order
    - _Requirements: 3.2_

  - [x] 4.3 Update `app/api/admin.py` PATCH handler to call module-level hydration functions
    - Replace `app_state.hydrate_jellyfin_from_db(db)` and `app_state.hydrate_audio_config_from_db(db)` with the module-level equivalents imported from `app.state`
    - _Requirements: 3.4_

- [x] 5. Checkpoint — ensure all tests pass after AppState and upsert changes
  - Run `uv run pytest` and `uv run ruff check`; resolve any failures before continuing.

- [x] 6. Add `get_credentials(db)` to `PlatformConnector`; delete credential if-chains and `_platform_config()`
  - [x] 6.1 Add abstract `get_credentials` method to `app/platforms/base.py`
    - Add `from sqlalchemy.orm import Session` import
    - Add `@abstractmethod def get_credentials(self, db: Session) -> tuple[str | None, str | None]: ...` to `PlatformConnector`
    - _Requirements: 2.3_

  - [x] 6.2 Implement `get_credentials` in `app/platforms/spotify.py`
    - Add `from sqlalchemy.orm import Session` and `from app.services.app_config import get_effective_setting` imports
    - Implement `get_credentials(self, db: Session) -> tuple[str | None, str | None]` returning `(get_effective_setting(db, "spotify_client_id"), get_effective_setting(db, "spotify_client_secret"))`
    - _Requirements: 2.3_

  - [x] 6.3 Implement `get_credentials` in `app/platforms/youtube.py`
    - Add `from sqlalchemy.orm import Session` and `from app.services.app_config import get_effective_setting` imports
    - Implement `get_credentials(self, db: Session) -> tuple[str | None, str | None]` returning `(get_effective_setting(db, "google_client_id"), get_effective_setting(db, "google_client_secret"))`
    - _Requirements: 2.3_

  - [x] 6.4 Delete both credential if-chains from `app/services/sync_engine.py`
    - Remove the `if link.platform == "spotify": credentials = await connector.refresh_credentials(...)` and `if link.platform == "youtube": credentials = await connector.refresh_credentials(...)` blocks in `run_user_sync`
    - Replace with `client_id, client_secret = connector.get_credentials(db)` followed by `credentials = await connector.refresh_credentials(credentials=credentials, client_id=client_id, client_secret=client_secret)`
    - Remove the now-unused `from app.services.app_config import get_effective_setting` import from `sync_engine.py` if it is no longer referenced
    - _Requirements: 2.1, 2.2_

  - [x] 6.5 Delete `_platform_config()` from `app/api/platforms.py` and update OAuth routes
    - Replace `client_id, _ = _platform_config(db, platform)` in `start_oauth` with `client_id, _ = app_state.registry.get(platform).get_credentials(db)`
    - Replace `client_id, client_secret = _platform_config(db, platform)` in `complete_oauth_callback` with `client_id, client_secret = app_state.registry.get(platform).get_credentials(db)`
    - Delete the `_platform_config` function definition
    - Remove the now-unused `from app.services.app_config import get_effective_setting` import from `platforms.py` if no longer needed
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 6.6 Write property test for platform-agnostic credential refresh
    - **Property 4: Credential refresh is platform-agnostic from the caller's perspective**
    - **Validates: Requirements 2.2, 2.4**
    - Use an in-memory SQLite session; vary credentials dict content and expiry values; assert that calling `connector.refresh_credentials(credentials=creds, client_id=id, client_secret=secret)` returns a dict with at least an `access_token` key when input credentials are valid, for both `SpotifyConnector` and `YouTubeConnector` (mock the HTTP calls)
    - Tag: `# Feature: backend-refactor, Property 4`

- [x] 7. Checkpoint — ensure all tests pass after credential refactor
  - Run `uv run pytest` and `uv run ruff check`; resolve any failures before continuing.

- [x] 8. Session plumbing — pass caller's session to `_mark_task_downloading`, `_mark_task_terminal`, and `_persist_downloaded_track`
  - [x] 8.1 Add optional `db` parameter to `_mark_task_terminal` in `app/services/sync_engine.py`
    - Update signature to `def _mark_task_terminal(self, task_id: int, status: str, error_message: str | None, db: Session | None = None) -> None`
    - When `db` is provided use it directly; when absent fall back to `self.db_factory()` with the existing `try/finally s.close()` pattern
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 8.2 Add optional `db` parameter to `_mark_task_downloading` in `app/services/sync_engine.py` and make it async
    - Update signature to `async def _mark_task_downloading(self, task_id: int, db: Session | None = None) -> None`
    - When `db` is provided: wrap the write in `await asyncio.to_thread(_write, db)` using an inner `_write(s: Session)` function
    - When absent: open a new session via `self.db_factory()`, wrap in `asyncio.to_thread`, close in `finally`
    - This satisfies both Req 8.3 (method is now async) and Req 9.1
    - _Requirements: 8.3, 8.4, 9.1, 9.2, 9.3_

  - [x] 8.3 Update `download_many` and `_download` in `app/services/download.py` to treat `on_downloading` as async
    - Change the type annotation of `on_downloading` in both `download_many` and `_download` from `Callable[[int], None]` to `Callable[[int], Awaitable[None]]`
    - In `_download`, replace `await asyncio.to_thread(on_downloading, task_id)` with `await on_downloading(task_id)`
    - _Requirements: 8.1, 8.2_

  - [x] 8.4 Pass the active session to `_mark_task_terminal` and `_mark_task_downloading` in `run_user_sync`
    - In the `on_each_download_result` closure and the download phase of `run_user_sync`, pass `db=db` to both `_mark_task_terminal` and `_mark_task_downloading` calls
    - _Requirements: 9.4_

  - [x] 8.5 Refactor `_persist_downloaded_track` to accept a `Session` parameter
    - Update signature to `def _persist_downloaded_track(self, slots, req, path, playlist_track_paths, db: Session) -> bool`
    - Remove the `s: Session = self.db_factory()` open, the outer `try/finally s.close()`, and the `s.commit()` call (commit remains the caller's responsibility)
    - Replace the bare `s.rollback()` in the `IntegrityError` handler with `db.begin_nested()` savepoint pattern as shown in the design: wrap the `Track` insert in `with db.begin_nested():` so only the nested savepoint is rolled back on conflict, not the caller's transaction
    - Replace all `s.` references with `db.`
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [x] 8.6 Update `run_user_sync` to pass `db` to `_persist_downloaded_track`
    - In the `on_each_download_result` closure, change the `_persist_downloaded_track(slots, req, path, playlist_track_paths)` call to `_persist_downloaded_track(slots, req, path, playlist_track_paths, db)`
    - _Requirements: 13.2, 13.4_

  - [x] 8.7 Write property test for task status update — session source invariant
    - **Property 7: Task status update produces identical DB state regardless of session source**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4**
    - Use an in-memory SQLite session; vary task_id, status values, and error strings; assert that `_mark_task_terminal` with a passed session produces the same `task.status`, `task.error_message`, and `task.completed_at` as the fallback path
    - Tag: `# Feature: backend-refactor, Property 7`

  - [x] 8.8 Write property test for `_persist_downloaded_track` — session source invariant
    - **Property 9: `_persist_downloaded_track` produces identical track and playlist-link rows regardless of session source**
    - **Validates: Requirements 13.1, 13.2, 13.4**
    - Use an in-memory SQLite session; vary `DownloadRequest` fields and slot counts; assert the same `Track` row and `SyncedPlaylistTrack` rows are inserted
    - Tag: `# Feature: backend-refactor, Property 9`

- [x] 9. Checkpoint — ensure all tests pass after session plumbing changes
  - Run `uv run pytest` and `uv run ruff check`; resolve any failures before continuing.

- [x] 10. Deduplicate sync engine — extract `_sync_one_playlist` and delete `_sync_single_playlist`
  - [x] 10.1 Extract `_sync_one_playlist` private method in `app/services/sync_engine.py`
    - Create `async def _sync_one_playlist(self, db, user, synced, link, credentials, playlist_track_paths, download_queue, source_id_to_idx, source_id_slots) -> None` with the signature from the design
    - Move the per-playlist body from `run_user_sync` (credential refresh → Spotify-to-YouTube resolution → dedup queue building) into this method; the download execution, Jellyfin push, and webhook fire remain in `run_user_sync`
    - _Requirements: 1.1_

  - [x] 10.2 Update `run_user_sync` to call `_sync_one_playlist` for each enabled playlist
    - Replace the inline per-playlist loop body with a call to `_sync_one_playlist`
    - Wrap each call in `try/except Exception` to log and continue on failure (preserving Req 1.6 behaviour)
    - _Requirements: 1.2, 1.6_

  - [x] 10.3 Rewrite `run_single_playlist_sync` / `_sync_single_playlist` to call `_sync_one_playlist`
    - Update `run_single_playlist_sync` to look up the `synced`, `link`, and `credentials`, then call `_sync_one_playlist` for the one target playlist, followed by the download execution and Jellyfin push
    - Delete the `_sync_single_playlist` method entirely
    - _Requirements: 1.3, 1.4, 1.5_

  - [x] 10.4 Write property test — full-user sync processes every enabled playlist
    - **Property 1: Full-user sync processes every enabled playlist**
    - **Validates: Requirements 1.2**
    - Use an in-memory SQLite session and mock `DownloadService` / `JellyfinClient`; vary number of enabled playlists (1–20) and platform mix; assert each enabled playlist is processed exactly once
    - Tag: `# Feature: backend-refactor, Property 1`

  - [x] 10.5 Write property test — per-playlist outcome is independent of call path
    - **Property 2: Per-playlist sync outcome is independent of call path**
    - **Validates: Requirements 1.3, 1.5**
    - Vary track count and source_id values; assert that `DownloadTask` rows created and `SyncedPlaylistTrack` rows written are identical whether the playlist is processed via `run_user_sync` or `run_single_playlist_sync`
    - Tag: `# Feature: backend-refactor, Property 2`

  - [x] 10.6 Write property test — sync continues after per-playlist failure
    - **Property 3: Sync continues after per-playlist failure**
    - **Validates: Requirements 1.6**
    - Vary which playlist index raises and the exception type; assert remaining playlists are still processed and their download tasks created
    - Tag: `# Feature: backend-refactor, Property 3`

- [x] 11. Checkpoint — ensure all tests pass after sync engine deduplication
  - Run `uv run pytest` and `uv run ruff check`; resolve any failures before continuing.

- [x] 12. Add Pydantic response models to all route handlers
  - [x] 12.1 Add response models to `app/api/sync.py`
    - Define `SyncAccepted`, `QueueCounts`, `SyncStatusResponse`, `DownloadFailureItem`, `DownloadFailuresResponse`, and `SyncHistoryResponse` models in `sync.py`
    - Add `response_model=` to `manual_sync`, `sync_status`, `download_failures`, and `sync_history` route decorators
    - Ensure returned dicts are structurally identical to the previous responses for all existing fields
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 12.2 Add response models to `app/api/playlists.py`
    - Define `PlaylistItem`, `PlaylistsResponse`, and `ToggleResponse` models in `playlists.py`
    - Add `response_model=` to `list_playlists`, `toggle_playlist`, and `sync_playlist` route decorators
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 12.3 Add response models to `app/api/platforms.py`
    - Define `LinkedPlatform`, `PlatformsResponse`, `OAuthStartResponse`, and `UnlinkResponse` models in `platforms.py`
    - Add `response_model=` to `list_platforms`, `start_oauth`, and `unlink_platform` route decorators
    - Leave `complete_oauth_callback` (returns `RedirectResponse`) without a `response_model`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 12.4 Add response models to `app/api/admin.py`
    - Define `UserItem`, `UsersResponse`, `SystemInfoResponse`, `AdminSettingsResponse` (with `model_config = ConfigDict(extra="allow")`), and `SettingsUpdateResponse` models in `admin.py`
    - Add `response_model=` to `users`, `system_info`, `get_settings_view`, `get_effective_settings`, and `update_settings` route decorators
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 12.5 Add response models to `app/api/setup.py`
    - Define `SetupResponse` and `SetupStatusResponse` models in `setup.py`
    - Add `response_model=` to `configure_setup` and `setup_status` route decorators
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 12.6 Write property test — route responses are deserializable into their declared response models
    - **Property 8: Route responses are deserializable into their declared response models**
    - **Validates: Requirements 10.1, 10.2, 10.4**
    - Use `TestClient`; vary request parameters for a representative set of routes; assert that the JSON response body can be parsed by the declared response model without validation errors
    - Tag: `# Feature: backend-refactor, Property 8`

- [x] 13. Final checkpoint — full suite green, lint clean
  - Run `uv run pytest` and `uv run ruff check`; all tests must pass and no lint violations may remain.

---

## Notes

- Sub-tasks marked with `*` are optional and can be skipped for a faster pass; the implementation is complete without them.
- All property tests use in-memory SQLite (`sqlite:///:memory:`) and mock `DownloadService` / `JellyfinClient` to avoid I/O.
- Add `hypothesis` to `[dependency-groups] dev` in `pyproject.toml` and run `uv sync` before writing the first property test.
- Each task references specific requirements for traceability; the requirement numbers match `requirements.md`.
- No Alembic migrations are needed — all changes are in the service and API layers only.
