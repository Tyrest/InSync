# Requirements Document

## Introduction

This document defines requirements for a backend refactor of the InSync FastAPI application. The **primary goal is maximum code deletion** — every requirement targets the removal of dead code, duplicated logic, or unnecessary indirection. No externally visible API behaviour, data models, or user-facing functionality changes.

The refactor targets thirteen confirmed deletion opportunities identified by full codebase analysis:

1. **Sync engine duplication** — `run_user_sync` and `_sync_single_playlist` duplicate ~300 lines of identical logic; extract a shared method and delete the copy
2. **Platform credential if-chains** — the same `if link.platform == "spotify" / "youtube"` block appears twice in `sync_engine.py`; move credential lookup into each `PlatformConnector` and delete both branches
3. **AppState startup methods** — four methods (`hydrate_jellyfin_from_db`, `hydrate_audio_config_from_db`, `seed_jellyfin_from_env_if_db_incomplete`, `bootstrap_jwt_secret`) exist only to be called from `main.py`; inline them into `lifespan` and delete the methods
4. **AppConfig upsert pattern** — the `select / if row: row.value = v else: db.add(AppConfig(...))` pattern is duplicated in `admin.py`, `setup.py`, and `state.py`; replace all three with `set_setting()` and delete the inline copies
5. **Duplicate sync endpoint** — `POST /api/sync/playlist/{id}` in `sync.py` and `POST /api/playlists/{id}/sync` in `playlists.py` do the same thing; delete the one in `sync.py`
6. **Legacy path methods** — `legacy_mp3_path`, `flat_legacy_mp3_path`, and `expected_mp3_path` in `DownloadService` exist only for backward compatibility with old file layouts; delete them if no legacy files remain
7. **Dead helper function** — `_run_sync_in_background` in `sync.py` is defined but never called; delete it
8. **Async boundary inconsistency** — `on_downloading` is typed sync but called via `asyncio.to_thread`; unify with `on_each_result` as async and delete the `asyncio.to_thread` wrapper
9. **Per-call DB sessions in task marking** — `_mark_task_downloading` and `_mark_task_terminal` each open a fresh session for a single row update during an active sync; pass the session through and delete the redundant `db_factory()` calls
10. **Missing Pydantic response models** — every route returns an untyped `dict`; add typed models to remove the implicit untyped surface
11. **`_platform_config()` helper** — the if-chain in `platforms.py` that maps platform names to credential keys becomes dead code once credential lookup moves into `PlatformConnector`; delete it
12. **`import json` inside function body** — in `webhooks.py` the `import json` statement is inside the `if secret:` block; move it to the top-level imports
13. **`_persist_downloaded_track` opens a new DB session** — this method calls `self.db_factory()` for every downloaded track during an active sync; accept the caller's session and delete the redundant open/close

---

## Glossary

- **SyncEngine**: The `SyncEngine` class in `services/sync_engine.py` that orchestrates the full sync cycle (credential refresh → playlist fetch → download → Jellyfin push).
- **PlatformConnector**: The abstract base class in `platforms/base.py` that each platform (Spotify, YouTube) implements.
- **AppState**: The global singleton in `state.py` that holds shared service instances (`JellyfinClient`, `DownloadService`, `SyncEngine`, `PlatformRegistry`, `SchedulerService`).
- **AppConfig**: The SQLAlchemy model and key/value table used for DB-backed runtime configuration.
- **DownloadService**: The `DownloadService` class in `services/download.py` that wraps yt-dlp.
- **API_Router**: Any FastAPI `APIRouter` instance under `app/api/`.
- **Response_Model**: A Pydantic `BaseModel` subclass used as the `response_model` parameter on a FastAPI route.
- **Lifespan**: The FastAPI `lifespan` async context manager in `main.py` responsible for startup and shutdown.
- **set_setting**: The `set_setting()` helper in `services/app_config.py` that upserts a single `AppConfig` row.

---

## Requirements

### Requirement 1: Delete the Duplicate Sync Engine Method

**User Story:** As a maintainer, I want the sync logic to live in one place, so that ~300 lines of duplicated code are deleted and bug fixes only need to be made once.

#### Acceptance Criteria

1. THE SyncEngine SHALL contain a single shared method that encapsulates the per-playlist logic: credential refresh, Spotify-to-YouTube track resolution, deduplication queue building, download execution, and Jellyfin playlist push.
2. WHEN a full-user sync is triggered, THE SyncEngine SHALL invoke the shared per-playlist method for each of the user's enabled playlists.
3. WHEN a single-playlist sync is triggered, THE SyncEngine SHALL invoke the same shared per-playlist method for that one playlist.
4. THE `_sync_single_playlist` method SHALL be deleted from `SyncEngine` after its logic is merged into the shared method.
5. THE SyncEngine SHALL produce identical observable outcomes (download tasks created, tracks persisted, Jellyfin playlists updated, webhook fired) after the refactor as it did before.
6. IF the shared method raises an unhandled exception for one playlist, THEN THE SyncEngine SHALL log the error and continue processing remaining playlists in a full-user sync.

---

### Requirement 2: Delete Platform Credential If-Chains from SyncEngine

**User Story:** As a maintainer, I want the `if link.platform == "spotify" / "youtube"` credential blocks deleted from `sync_engine.py`, so that adding a new platform requires no changes to the sync engine.

#### Acceptance Criteria

1. THE `if link.platform == "spotify"` and `if link.platform == "youtube"` branches for credential refresh SHALL be deleted from `sync_engine.py`.
2. WHEN THE SyncEngine needs refreshed credentials for a platform, THE SyncEngine SHALL call a single method on the PlatformConnector without knowing which platform it is.
3. THE PlatformConnector SHALL accept a database session or a settings-lookup callable so it can retrieve its own `client_id` and `client_secret` without the caller providing them explicitly.
4. WHERE a PlatformConnector does not require credential refresh (e.g. a future API-key-only platform), THE PlatformConnector SHALL return the existing credentials unchanged from the refresh method.
5. WHEN Requirement 2 is implemented, THE `_platform_config()` helper in `platforms.py` SHALL also be deleted, as it becomes dead code (see Requirement 11).

---

### Requirement 3: Delete Startup Methods from AppState

**User Story:** As a maintainer, I want four startup methods deleted from `AppState`, so that `state.py` is a plain instance holder and startup logic is consolidated in one place.

#### Acceptance Criteria

1. THE `hydrate_jellyfin_from_db`, `hydrate_audio_config_from_db`, `seed_jellyfin_from_env_if_db_incomplete`, and `bootstrap_jwt_secret` methods SHALL be deleted from `AppState`.
2. THE Lifespan SHALL call the same hydration, seeding, and bootstrap operations directly (inlined or as module-level functions), preserving the existing call order.
3. AFTER the refactor, THE AppState class SHALL only hold references to shared service instances: `registry`, `downloader`, `jellyfin`, `sync_engine`, and `scheduler`.
4. WHEN the admin settings PATCH endpoint updates Jellyfin or audio config, THE API_Router SHALL call the extracted hydration functions directly rather than methods on AppState.

---

### Requirement 4: Delete Inline AppConfig Upsert Copies

**User Story:** As a maintainer, I want the duplicated `select / if row: row.value = v else: db.add(AppConfig(...))` pattern deleted from three files, so that config persistence logic lives only in `set_setting()`.

#### Acceptance Criteria

1. THE inline `AppConfig` upsert pattern SHALL be deleted from `admin.py` and replaced with calls to `set_setting` from `services/app_config.py`.
2. THE inline `AppConfig` upsert pattern SHALL be deleted from `setup.py` and replaced with calls to `set_setting` from `services/app_config.py`.
3. THE inline `AppConfig` upsert pattern SHALL be deleted from `state.py` (JWT secret bootstrap and env seeding) and replaced with calls to `set_setting` from `services/app_config.py`.
4. AFTER the refactor, no module outside of `services/app_config.py` SHALL construct `AppConfig(key=..., value=...)` instances and add them to the session directly.
5. THE `set_setting` function SHALL remain the single authoritative implementation of the upsert pattern for `AppConfig` rows.

---

### Requirement 5: Delete the Duplicate Single-Playlist Sync Endpoint

**User Story:** As a maintainer, I want `POST /api/sync/playlist/{id}` deleted from `sync.py`, so that there is one canonical route and the two implementations cannot diverge.

#### Acceptance Criteria

1. THE `sync_single_playlist` route handler and its `@router.post("/playlist/{synced_playlist_id}")` registration SHALL be deleted from `sync.py`.
2. THE `POST /api/playlists/{id}/sync` endpoint in `playlists.py` SHALL remain as the single canonical route for triggering a single-playlist sync.
3. THE deleted endpoint (`POST /api/sync/playlist/{id}`) SHALL return HTTP 404 after the refactor.
4. THE remaining single-playlist sync endpoint SHALL continue to return HTTP 202 on success and HTTP 409 when a sync is already running for the user.

---

### Requirement 6: Delete Legacy Path Methods from DownloadService

**User Story:** As a maintainer, I want `legacy_mp3_path`, `flat_legacy_mp3_path`, and `expected_mp3_path` deleted from `DownloadService`, so that backward-compatibility shims for old file layouts no longer exist in the codebase.

#### Acceptance Criteria

1. THE `legacy_mp3_path`, `flat_legacy_mp3_path`, and `expected_mp3_path` methods SHALL be deleted from `DownloadService` once it is confirmed that no callers outside `first_existing_audio_path` depend on them.
2. THE `first_existing_audio_path` method SHALL be updated to inline any path construction it previously delegated to the deleted methods, preserving the same candidate lookup order.
3. WHEN `first_existing_audio_path` is called with a valid track, THE DownloadService SHALL still check the new flat layout first, then the legacy 3-level layout, returning the first existing file.
4. IF no legacy files exist on disk (i.e. the deployment has been running on the current layout long enough), THEN THE `first_existing_audio_path` method MAY remove the legacy candidate entirely in a follow-up, but SHALL NOT do so as part of this requirement without explicit confirmation.

---

### Requirement 7: Delete the Dead `_run_sync_in_background` Helper

**User Story:** As a maintainer, I want the unused `_run_sync_in_background` function deleted from `sync.py`, so that dead code does not mislead future readers.

#### Acceptance Criteria

1. THE `_run_sync_in_background` function SHALL be deleted from `sync.py`.
2. WHEN the `manual_sync` endpoint triggers a background sync, THE API_Router SHALL continue to call `loop.create_task(...)` inline, as it already does.
3. AFTER deletion, no reference to `_run_sync_in_background` SHALL remain anywhere in the codebase.

---

### Requirement 8: Delete the `asyncio.to_thread` Wrapper for `on_downloading`

**User Story:** As a maintainer, I want the `asyncio.to_thread(on_downloading, task_id)` call deleted and the callback unified as async, so that the download pipeline has a consistent async boundary.

#### Acceptance Criteria

1. THE `on_downloading` callback parameter in `DownloadService.download_many` and `DownloadService._download` SHALL be typed as `Callable[[int], Awaitable[None]]`, consistent with `on_each_result`.
2. THE `asyncio.to_thread(on_downloading, task_id)` call SHALL be deleted from `DownloadService._download` and replaced with a direct `await on_downloading(task_id)`.
3. THE SyncEngine's `_mark_task_downloading` method SHALL be declared `async` to satisfy the updated callback type.
4. WHEN `_mark_task_downloading` performs a database write, THE blocking DB call SHALL be executed via `asyncio.to_thread` internally, keeping the public interface async and the blocking work off the event loop.

---

### Requirement 9: Delete Redundant DB Session Opens in SyncEngine Task Marking

**User Story:** As a maintainer, I want the unnecessary `self.db_factory()` calls inside `_mark_task_downloading` and `_mark_task_terminal` deleted when a session is already active, so that the sync run does not open extra short-lived connections for single-row updates.

#### Acceptance Criteria

1. THE SyncEngine `_mark_task_downloading` and `_mark_task_terminal` methods SHALL accept an optional `Session` parameter.
2. WHEN a `Session` is provided, THE SyncEngine SHALL use it directly for the status update and SHALL NOT call `self.db_factory()`.
3. WHEN no `Session` is provided, THE SyncEngine SHALL fall back to opening a new session via `db_factory`, preserving backward compatibility.
4. THE SyncEngine `run_user_sync` method SHALL pass its active `Session` to `_mark_task_downloading` and `_mark_task_terminal` during the download phase, eliminating the extra `db_factory()` calls for every task status update.

---

### Requirement 10: Add Pydantic Response Models to All Route Handlers

**User Story:** As a maintainer, I want route handlers to declare typed response models, so that the OpenAPI schema is accurate and response shape regressions are caught at development time.

#### Acceptance Criteria

1. THE API_Router SHALL declare a `response_model` on every route handler that currently returns a plain `dict`.
2. WHEN a Response_Model is added to a route, THE API_Router SHALL return data that is structurally identical to the previous untyped `dict` response for all existing fields.
3. THE Response_Model classes SHALL be defined in the same file as the router that uses them, or in a dedicated `app/api/schemas.py` module if shared across multiple routers.
4. WHEN the OpenAPI schema is generated (via `/openapi.json`), THE API_Router SHALL produce a schema that includes all response field names and types for every endpoint.
5. IF a route handler returns a union of response shapes (e.g. success vs. error), THEN THE API_Router SHALL use the success shape as the `response_model` and rely on `HTTPException` for error responses.

---

### Requirement 11: Delete `_platform_config()` from `platforms.py`

**User Story:** As a maintainer, I want the `_platform_config()` if-chain helper deleted from `platforms.py` once credential lookup moves into each `PlatformConnector`, so that the platform-name-to-credential-key mapping does not exist in two places.

#### Acceptance Criteria

1. THE `_platform_config` function SHALL be deleted from `platforms.py` after Requirement 2 is implemented and credential lookup has moved into each `PlatformConnector`.
2. WHEN `start_oauth` and `complete_oauth_callback` need platform credentials, THE API_Router SHALL retrieve them via the `PlatformConnector` interface rather than calling `_platform_config` directly.
3. AFTER deletion, no reference to `_platform_config` SHALL remain anywhere in the codebase.
4. THE OAuth flow (start and callback) SHALL continue to return HTTP 400 when platform credentials are not configured by the admin.

---

### Requirement 12: Move `import json` to Module Level in `webhooks.py`

**User Story:** As a maintainer, I want the `import json` statement moved out of the `if secret:` block in `webhooks.py`, so that imports are at the top of the file as per Python convention.

#### Acceptance Criteria

1. THE `import json` statement SHALL be moved to the top-level imports section of `webhooks.py`.
2. THE `if secret:` block SHALL retain its HMAC signing logic unchanged; only the import location changes.
3. AFTER the move, `webhooks.py` SHALL pass `ruff check` with no import-order or import-placement violations.

---

### Requirement 13: Delete Redundant DB Session Opens in `_persist_downloaded_track`

**User Story:** As a maintainer, I want the `self.db_factory()` call inside `_persist_downloaded_track` deleted when a session is already active, so that every downloaded track does not open and close an extra DB connection.

#### Acceptance Criteria

1. THE `_persist_downloaded_track` method SHALL accept a `Session` parameter from the caller instead of opening a new session via `self.db_factory()`.
2. WHEN `run_user_sync` calls `_persist_downloaded_track`, THE SyncEngine SHALL pass its active `Session` directly, eliminating the per-track `db_factory()` call.
3. THE `_persist_downloaded_track` method SHALL NOT call `s.close()` on a session it did not open; session lifecycle management remains the caller's responsibility.
4. THE track insert and playlist-link operations performed by `_persist_downloaded_track` SHALL remain within the caller's transaction, committing at the same point as before.
5. IF an `IntegrityError` occurs during track insert, THE SyncEngine SHALL still roll back only the nested savepoint and recover the existing track row, without closing the caller's session.
