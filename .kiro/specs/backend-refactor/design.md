# Design Document — Backend Refactor

## Overview

This refactor removes dead code, duplicated logic, and unnecessary indirection from the InSync FastAPI backend. No externally visible API behaviour, data models, or database schema changes. The thirteen requirements map to concrete deletions and small structural moves across eight files.

The guiding principle: every change must result in fewer lines of code and no new behaviour.

---

## Architecture

The existing layered architecture is unchanged:

```
main.py (lifespan)
  └── AppState (state.py)          ← becomes a plain instance holder
        ├── SyncEngine             ← duplicate method deleted, session plumbing simplified
        ├── DownloadService        ← legacy path methods deleted, async boundary unified
        ├── JellyfinClient
        └── PlatformRegistry
              ├── SpotifyConnector ← gains get_credentials(db) method
              └── YouTubeConnector ← gains get_credentials(db) method

app/api/
  ├── sync.py        ← duplicate endpoint + dead helper deleted; response models added
  ├── playlists.py   ← response models added
  ├── platforms.py   ← _platform_config() deleted; response models added
  ├── admin.py       ← inline upsert replaced with set_setting(); response models added
  └── setup.py       ← inline upsert replaced with set_setting(); response models added

app/services/
  ├── app_config.py  ← set_setting() already exists; no changes needed
  └── webhooks.py    ← import json moved to module level
```

---

## Components and Interfaces

### Req 1 — Delete `_sync_single_playlist` (sync_engine.py)

**Current state:** `run_user_sync` (~200 lines) and `_sync_single_playlist` (~150 lines) duplicate the per-playlist loop: credential refresh → Spotify-to-YouTube resolution → dedup queue → download → Jellyfin push.

**Change:** Extract a new private method `_sync_one_playlist` that handles a single `SyncedPlaylist`. Both `run_user_sync` and `run_single_playlist_sync` call it. Delete `_sync_single_playlist`.

New method signature:

```python
async def _sync_one_playlist(
    self,
    db: Session,
    user: User,
    synced: SyncedPlaylist,
    link: PlatformLink,
    credentials: dict,
    playlist_track_paths: dict[int, list[str | None]],
    download_queue: list[tuple[DownloadRequest, int]],
    source_id_to_idx: dict[str, int],
    source_id_slots: dict[str, list[tuple[int, int]]],
) -> None: ...
```

`run_user_sync` iterates over all enabled playlists, calls `_sync_one_playlist` for each, wraps each call in a `try/except` to log and continue on failure (Req 1.6). `run_single_playlist_sync` calls it for the one target playlist.

The download execution, Jellyfin push, and webhook fire remain in `run_user_sync` / `run_single_playlist_sync` respectively — they are not per-playlist concerns.

**Deleted:** `_sync_single_playlist` method (~150 lines).

---

### Req 2 + Req 11 — Delete credential if-chains; delete `_platform_config()` (sync_engine.py, platforms.py, base.py, spotify.py, youtube.py)

**Current state:** `sync_engine.py` contains two identical `if link.platform == "spotify" / "youtube"` blocks that call `get_effective_setting` to retrieve `client_id` / `client_secret` before calling `connector.refresh_credentials(credentials=..., client_id=..., client_secret=...)`. `platforms.py` has `_platform_config()` doing the same key mapping for OAuth.

**Change:** Add a `get_credentials(db: Session) -> tuple[str | None, str | None]` method to `PlatformConnector` (abstract base). Each connector implements it to look up its own keys:

```python
# base.py — new abstract method
@abstractmethod
def get_credentials(self, db: Session) -> tuple[str | None, str | None]:
    """Return (client_id, client_secret) for this platform from DB/env."""
    ...
```

```python
# spotify.py
def get_credentials(self, db: Session) -> tuple[str | None, str | None]:
    return (
        get_effective_setting(db, "spotify_client_id"),
        get_effective_setting(db, "spotify_client_secret"),
    )
```

```python
# youtube.py
def get_credentials(self, db: Session) -> tuple[str | None, str | None]:
    return (
        get_effective_setting(db, "google_client_id"),
        get_effective_setting(db, "google_client_secret"),
    )
```

`sync_engine.py` replaces both if-chains with:

```python
client_id, client_secret = connector.get_credentials(db)
credentials = await connector.refresh_credentials(
    credentials=credentials,
    client_id=client_id,
    client_secret=client_secret,
)
```

`platforms.py` replaces `_platform_config(db, platform)` calls with `connector.get_credentials(db)` and deletes the `_platform_config` function.

**Deleted:** both `if link.platform ==` credential blocks in `sync_engine.py` (~12 lines × 2); `_platform_config()` in `platforms.py` (~10 lines).

---

### Req 3 — Delete startup methods from AppState (state.py, main.py)

**Current state:** `AppState` has four methods called only from `lifespan` in `main.py`:
- `bootstrap_jwt_secret(db)`
- `seed_jellyfin_from_env_if_db_incomplete(db)`
- `hydrate_jellyfin_from_db(db)`
- `hydrate_audio_config_from_db(db)`

`hydrate_jellyfin_from_db` and `hydrate_audio_config_from_db` are also called from the admin PATCH handler.

**Change:** Move all four as module-level functions in `state.py` (not methods on `AppState`). `AppState.__init__` and `AppState.scheduler` remain; the class becomes a plain holder.

```python
# state.py — module-level functions replacing the methods
def bootstrap_jwt_secret(db: Session) -> str: ...
def seed_jellyfin_from_env_if_db_incomplete(db: Session) -> None: ...
def hydrate_jellyfin_from_db(db: Session) -> None: ...
def hydrate_audio_config_from_db(db: Session) -> None: ...
```

`main.py` lifespan calls them as `bootstrap_jwt_secret(db)` etc. (same call order as before).

`admin.py` PATCH handler imports and calls `hydrate_jellyfin_from_db(db)` and `hydrate_audio_config_from_db(db)` directly.

**Deleted:** four instance methods from `AppState` (~50 lines total).

---

### Req 4 — Delete inline AppConfig upsert copies (admin.py, setup.py, state.py)

**Current state:** Three files contain the pattern:
```python
row = db.scalar(select(AppConfig).where(AppConfig.key == key))
if row:
    row.value = value
else:
    db.add(AppConfig(key=key, value=value))
```

`set_setting(db, key, value)` in `services/app_config.py` already implements this exactly.

**Changes:**

`admin.py` — `update_settings` loop body:
```python
# before
for key, value in changes.items():
    row = db.scalar(select(AppConfig).where(AppConfig.key == key))
    if row:
        row.value = str(value)
    else:
        db.add(AppConfig(key=key, value=str(value)))

# after
for key, value in changes.items():
    set_setting(db, key, str(value))
```

`setup.py` — `configure_setup` body:
```python
# before
for key, value in {"jellyfin_url": ..., "jellyfin_api_key": ...}.items():
    row = db.scalar(select(AppConfig).where(AppConfig.key == key))
    if row:
        row.value = value
    else:
        db.add(AppConfig(key=key, value=value))

# after
set_setting(db, "jellyfin_url", str(payload.jellyfin_url))
set_setting(db, "jellyfin_api_key", payload.jellyfin_api_key)
```

`state.py` — `seed_jellyfin_from_env_if_db_incomplete` and `bootstrap_jwt_secret` (now module-level functions after Req 3) replace their inline upserts with `set_setting(db, key, value)`.

**Deleted:** ~30 lines of duplicated upsert code across three files. `AppConfig` direct construction removed from all callers outside `app_config.py`.

---

### Req 5 — Delete duplicate `POST /api/sync/playlist/{id}` (sync.py)

**Current state:** `sync.py` has `sync_single_playlist` at `POST /playlist/{synced_playlist_id}`. `playlists.py` has `sync_playlist` at `POST /{playlist_id}/sync`. They are identical in behaviour.

**Change:** Delete the `sync_single_playlist` handler and its `@router.post` registration from `sync.py`. The canonical route remains `POST /api/playlists/{id}/sync`.

**Deleted:** ~10 lines from `sync.py`.

---

### Req 6 — Delete legacy path methods from DownloadService (download.py)

**Current state:** `legacy_mp3_path`, `flat_legacy_mp3_path`, and `expected_mp3_path` are only called from `first_existing_audio_path`. No external callers.

**Change:** Inline the path construction into `first_existing_audio_path` and delete the three methods:

```python
def first_existing_audio_path(self, title: str, artist: str, album: str, source_id: str) -> Path | None:
    candidates = [
        self.unique_audio_path(title, artist, album, source_id),
        # flat legacy: music_dir / artist / title.mp3
        self.music_dir / _safe_name(artist) / f"{_safe_name(title)}.mp3",
        # 3-level legacy: music_dir / artist / album / title.mp3
        self.music_dir / _safe_name(artist) / _safe_name(album) / f"{_safe_name(title)}.mp3",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None
```

**Deleted:** `legacy_mp3_path`, `flat_legacy_mp3_path`, `expected_mp3_path` (~12 lines).

---

### Req 7 — Delete `_run_sync_in_background` (sync.py)

**Current state:** `_run_sync_in_background` is defined but never called. `manual_sync` already inlines `loop.create_task(...)`.

**Change:** Delete the function.

**Deleted:** ~4 lines.

---

### Req 8 — Unify `on_downloading` as async (download.py, sync_engine.py)

**Current state:** `on_downloading` is typed `Callable[[int], None]` and called via `asyncio.to_thread(on_downloading, task_id)`. `on_each_result` is already `Callable[[int, DownloadResult], Awaitable[None]]`.

**Changes:**

`download.py` — update type and call site:
```python
# download_many signature
async def download_many(
    self,
    items: list[tuple[DownloadRequest, int]],
    on_downloading: Callable[[int], Awaitable[None]] | None = None,
    on_each_result: Callable[[int, DownloadResult], Awaitable[None]] | None = None,
) -> list[DownloadResult]: ...

# _download — replace asyncio.to_thread call
if on_downloading is not None:
    await on_downloading(task_id)   # was: await asyncio.to_thread(on_downloading, task_id)
```

`sync_engine.py` — `_mark_task_downloading` becomes async; the blocking DB write moves inside `asyncio.to_thread`:
```python
async def _mark_task_downloading(self, task_id: int, db: Session | None = None) -> None:
    def _write(s: Session) -> None:
        task = s.get(DownloadTask, task_id)
        if task:
            task.status = DownloadStatus.DOWNLOADING.value
            s.commit()

    if db is not None:
        await asyncio.to_thread(_write, db)
    else:
        s: Session = self.db_factory()
        try:
            await asyncio.to_thread(_write, s)
        finally:
            s.close()
```

**Deleted:** `asyncio.to_thread` wrapper at the call site in `_download` (~1 line changed).

---

### Req 9 — Pass session to `_mark_task_downloading` and `_mark_task_terminal` (sync_engine.py)

**Current state:** Both methods open a fresh `self.db_factory()` session for a single row update, even when called from within an active sync that already holds a session.

**Change:** Add an optional `db: Session | None = None` parameter to both methods. When provided, use it directly; when absent, fall back to `db_factory()`.

```python
async def _mark_task_downloading(self, task_id: int, db: Session | None = None) -> None:
    # (shown above in Req 8)

def _mark_task_terminal(
    self, task_id: int, status: str, error_message: str | None, db: Session | None = None
) -> None:
    def _write(s: Session) -> None:
        task = s.get(DownloadTask, task_id)
        if task:
            task.status = status
            task.error_message = error_message
            task.completed_at = datetime.now(UTC)
            s.commit()

    if db is not None:
        _write(db)
    else:
        s: Session = self.db_factory()
        try:
            _write(s)
        finally:
            s.close()
```

`run_user_sync` passes `db` to both methods in the `on_each_download_result` closure and in the download phase.

**Deleted:** redundant `db_factory()` open/close pairs for every task status update during a sync run.

---

### Req 10 — Add Pydantic response models to all route handlers

**Current state:** Every route returns an untyped `dict`. FastAPI generates no schema for response bodies.

**Change:** Define `BaseModel` subclasses in each router file (or a shared `app/api/schemas.py` if used across multiple routers). Add `response_model=` to every `@router.get/post/patch/delete` decorator.

Key models per file:

**sync.py**
```python
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
```

**playlists.py**
```python
class PlaylistItem(BaseModel):
    id: int
    platform: str
    name: str
    enabled: bool
    last_synced: str | None

class PlaylistsResponse(BaseModel):
    playlists: list[PlaylistItem]

class ToggleResponse(BaseModel):
    status: str
```

**platforms.py**
```python
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
```

**admin.py**
```python
class UserItem(BaseModel):
    id: int
    jellyfin_user_id: str
    username: str
    is_admin: bool

class UsersResponse(BaseModel):
    users: list[UserItem]

class SystemInfoResponse(BaseModel):
    music_dir_exists: bool
    data_dir_exists: bool
    download_tasks: int
    download_concurrency: int

class AdminSettingsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")  # dynamic keys from AppConfig

class SettingsUpdateResponse(BaseModel):
    status: str
```

**setup.py**
```python
class SetupResponse(BaseModel):
    status: str

class SetupStatusResponse(BaseModel):
    configured: bool
```

Routes that return `RedirectResponse` (OAuth callback) are excluded — FastAPI does not apply `response_model` to redirect responses.

---

### Req 12 — Move `import json` to module level (webhooks.py)

**Current state:**
```python
if secret:
    import json
    body = json.dumps(payload, ...).encode()
```

**Change:** Move `import json` to the top-level imports block. The `if secret:` block body is otherwise unchanged.

---

### Req 13 — Pass caller's session to `_persist_downloaded_track` (sync_engine.py)

**Current state:** `_persist_downloaded_track` opens `self.db_factory()` for every downloaded track, even though the caller (`run_user_sync`) already holds an active session.

**Change:** Accept a `Session` parameter from the caller. Remove the internal `db_factory()` call, `s.close()`, and the outer `try/finally`. The `IntegrityError` rollback uses `db.begin_nested()` (savepoint) so the caller's transaction is not aborted.

```python
def _persist_downloaded_track(
    self,
    slots: list[tuple[int, int]],
    req: DownloadRequest,
    path: Path,
    playlist_track_paths: dict[int, list[str | None]],
    db: Session,
) -> bool:
    track_id: int | None = None
    file_path_str = str(path)
    try:
        with db.begin_nested():   # savepoint
            track = Track(...)
            db.add(track)
            db.flush()
            track_id = track.id
    except IntegrityError:
        existing = db.scalar(select(Track).where(Track.source_id == req.source_id))
        if existing:
            track_id = existing.id
            file_path_str = existing.file_path
        else:
            return False
    for playlist_id, pos in slots:
        playlist_track_paths[playlist_id][pos] = file_path_str
        db.add(SyncedPlaylistTrack(...))
    return True
```

`run_user_sync` passes `db` when calling `_persist_downloaded_track`. The caller commits at the same point as before (end of `on_each_download_result`).

**Deleted:** `s = self.db_factory()`, `try/finally s.close()`, and the outer exception handler (~15 lines).

---

## Data Models

No changes to SQLAlchemy models or Alembic migrations. All changes are in service and API layers only.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Full-user sync processes every enabled playlist

*For any* user with N enabled playlists, running `run_user_sync` should result in each of those N playlists being processed (credential refresh attempted, tracks queued or resolved) exactly once.

**Validates: Requirements 1.2**

---

### Property 2: Per-playlist sync outcome is independent of call path

*For any* single enabled playlist, the set of `DownloadTask` rows created and `SyncedPlaylistTrack` rows written should be identical whether the playlist is processed via `run_user_sync` (full-user path) or `run_single_playlist_sync` (single-playlist path).

**Validates: Requirements 1.3, 1.5**

---

### Property 3: Sync continues after per-playlist failure

*For any* list of playlists where one raises an exception during processing, the remaining playlists should still be processed and their download tasks created.

**Validates: Requirements 1.6**

---

### Property 4: Credential refresh is platform-agnostic from the caller's perspective

*For any* `PlatformConnector` implementation, calling `connector.refresh_credentials(credentials=creds, client_id=id, client_secret=secret)` should return a dict that contains at least an `access_token` key when the input credentials are valid, without the caller needing to know the platform name.

**Validates: Requirements 2.2, 2.4**

---

### Property 5: `set_setting` upsert is idempotent

*For any* key/value pair, calling `set_setting(db, key, value)` twice with different values should result in exactly one `AppConfig` row for that key, containing the second value.

**Validates: Requirements 4.1, 4.2, 4.3, 4.5**

---

### Property 6: `first_existing_audio_path` returns highest-priority existing path

*For any* combination of candidate paths (new flat, flat legacy, 3-level legacy) where at least one exists on disk, `first_existing_audio_path` should return the new flat path if it exists, otherwise the flat legacy path if it exists, otherwise the 3-level legacy path.

**Validates: Requirements 6.2, 6.3**

---

### Property 7: Task status update produces identical DB state regardless of session source

*For any* `DownloadTask` row and target status, calling `_mark_task_terminal(task_id, status, error, db=session)` with a passed session should produce the same `task.status`, `task.error_message`, and `task.completed_at` values as the previous path that opened a new session internally.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4**

---

### Property 8: Route responses are deserializable into their declared response models

*For any* valid request to a route handler that declares a `response_model`, the JSON response body should be deserializable into that model without validation errors.

**Validates: Requirements 10.1, 10.2, 10.4**

---

### Property 9: `_persist_downloaded_track` produces identical track and playlist-link rows regardless of session source

*For any* `DownloadRequest` and list of playlist slots, calling `_persist_downloaded_track(slots, req, path, paths, db=session)` with a passed session should insert the same `Track` row and `SyncedPlaylistTrack` rows as the previous path that opened a new session internally.

**Validates: Requirements 13.1, 13.2, 13.4**

---

## Error Handling

All error handling behaviour is preserved unchanged:

- **Credential refresh failure** — `sync_engine.py` logs and skips the platform (existing `except Exception` block retained).
- **Per-playlist failure** — after Req 1, the `run_user_sync` loop wraps each `_sync_one_playlist` call in `try/except` and logs before continuing.
- **Download failure** — `on_each_download_result` marks the task `FAILED` and logs; other downloads continue.
- **Track persist conflict** — `_persist_downloaded_track` uses a savepoint (`begin_nested`) to recover from `IntegrityError` without aborting the caller's transaction.
- **OAuth errors** — `platforms.py` returns HTTP 400 when `client_id` / `client_secret` are absent (behaviour unchanged after `_platform_config` is replaced by `connector.get_credentials(db)`).
- **Webhook failure** — best-effort; exceptions are caught and logged, never propagated.

---

## Testing Strategy

This is a refactor with no new external behaviour, so the testing strategy focuses on regression prevention.

### Unit tests (example-based)

Each deletion should be covered by at least one existing or new example test:

- `POST /api/sync/playlist/{id}` returns 404 after Req 5 (new test in `test_api.py`)
- `AppState` no longer has the four startup methods (attribute check)
- `_run_sync_in_background` no longer exists in `sync.py` (attribute check)
- `_platform_config` no longer exists in `platforms.py` (attribute check)
- Admin PATCH with `jellyfin_url` updates `app_state.jellyfin.base_url` (existing test extended)
- `webhooks.py` HMAC signing still produces a valid signature after `import json` move

### Property-based tests

Use [Hypothesis](https://hypothesis.readthedocs.io/) (already available in the Python ecosystem; add to `pyproject.toml` dev dependencies).

Each property test runs a minimum of 100 iterations. Tag format: `# Feature: backend-refactor, Property N: <text>`.

| Property | Test location | What varies |
|---|---|---|
| P1: Full-user sync processes every enabled playlist | `tests/test_sync_engine.py` | Number of playlists (1–20), platform mix |
| P2: Per-playlist outcome independent of call path | `tests/test_sync_engine.py` | Track count, source_id values |
| P3: Sync continues after per-playlist failure | `tests/test_sync_engine.py` | Which playlist index raises, exception type |
| P4: Credential refresh is platform-agnostic | `tests/test_platforms.py` | Credentials dict content, expiry values |
| P5: `set_setting` upsert is idempotent | `tests/test_app_config.py` | Key names, value strings |
| P6: `first_existing_audio_path` priority | `tests/test_download.py` | Which candidate paths exist on disk |
| P7: Task status update — session source invariant | `tests/test_sync_engine.py` | task_id, status values, error strings |
| P8: Route responses deserializable into response models | `tests/test_api.py` | Request parameters |
| P9: `_persist_downloaded_track` — session source invariant | `tests/test_sync_engine.py` | DownloadRequest fields, slot counts |

All property tests use in-memory SQLite (`sqlite:///:memory:`) and mock `DownloadService` / `JellyfinClient` to avoid I/O. No AWS or external service calls.

### Regression guard

Run the full existing test suite (`uv run pytest`) after each requirement is implemented. The suite must remain green throughout. Ruff lint (`uv run ruff check`) must pass with no new violations.
