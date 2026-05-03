# Project Structure

```
insync/
├── backend/                    # Python FastAPI application
│   ├── app/
│   │   ├── api/                # Route handlers (one file per feature area)
│   │   │   ├── __init__.py     # Assembles api_router with prefix /api
│   │   │   ├── auth.py         # Login, /me
│   │   │   ├── admin.py        # Admin-only endpoints
│   │   │   ├── config_client.py
│   │   │   ├── dashboard.py
│   │   │   ├── library.py
│   │   │   ├── platforms.py    # OAuth connect/disconnect
│   │   │   ├── playlists.py
│   │   │   ├── setup.py        # First-run wizard
│   │   │   └── sync.py         # Manual sync trigger
│   │   ├── core/
│   │   │   ├── dependencies.py # FastAPI Depends: get_current_user, require_admin
│   │   │   ├── scheduler.py    # APScheduler wrapper
│   │   │   └── security.py     # JWT encode/decode
│   │   ├── models/             # SQLAlchemy ORM models (one file per table)
│   │   ├── platforms/
│   │   │   ├── base.py         # PlatformConnector ABC + TrackInfo/PlaylistInfo dataclasses
│   │   │   ├── registry.py     # PlatformRegistry (keyed dict of connectors)
│   │   │   ├── spotify.py
│   │   │   └── youtube.py
│   │   ├── services/
│   │   │   ├── app_config.py   # DB-backed key/value config helpers
│   │   │   ├── download.py     # yt-dlp wrapper, AudioConfig, DownloadService
│   │   │   ├── jellyfin.py     # JellyfinClient (httpx)
│   │   │   ├── metadata.py     # mutagen/Pillow tag writing
│   │   │   ├── oauth_state.py
│   │   │   ├── sync_engine.py  # Orchestrates full sync cycle
│   │   │   └── webhooks.py
│   │   ├── config.py           # pydantic-settings Settings + get_settings()
│   │   ├── database.py         # SQLAlchemy engine, SessionLocal, Base, get_db()
│   │   ├── main.py             # FastAPI app, lifespan, SPA catch-all
│   │   ├── state.py            # AppState singleton (app_state)
│   │   └── version.py
│   ├── alembic/                # DB migrations
│   │   └── versions/
│   ├── tests/                  # pytest tests (FastAPI TestClient)
│   ├── data/                   # SQLite DB (gitignored in prod, present locally)
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/                   # React + TypeScript SPA
│   ├── src/
│   │   ├── api/
│   │   │   └── client.ts       # apiFetch, formatApiError, redirectToLogin
│   │   ├── components/         # Shared/reusable UI components
│   │   ├── config/
│   │   │   └── baseUrl.ts      # Reads window.__BASE_URL__ for subpath support
│   │   ├── pages/              # One file per route (Dashboard, Playlists, etc.)
│   │   ├── stores/
│   │   │   └── authStore.ts    # Zustand auth store (token + me)
│   │   ├── types/
│   │   │   └── index.ts        # Shared TypeScript types mirroring API responses
│   │   ├── App.tsx             # Router, RequireAuth, setup redirect
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
├── volumes/                    # Docker bind-mount targets (gitignored data)
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Key Conventions

### Backend

- **Settings**: always import via `get_settings()` — never instantiate `Settings` directly.
- **DB sessions**: use `Depends(get_db)` in route handlers; pass `Session` explicitly into services.
- **Global state**: `app_state` (singleton in `state.py`) holds `JellyfinClient`, `DownloadService`, `SyncEngine`, `PlatformRegistry`, and the scheduler.
- **Auth guards**: use `Depends(get_current_user)` for authenticated routes, `Depends(require_admin)` for admin-only routes.
- **New platforms**: subclass `PlatformConnector` (in `platforms/base.py`) and register in `PlatformRegistry`.
- **Models**: use SQLAlchemy 2.x `Mapped` / `mapped_column` style; one model per file under `app/models/`.
- **Migrations**: every schema change needs an Alembic migration in `alembic/versions/`.
- **Line length**: 120 characters (Ruff enforced).

### Frontend

- **API calls**: always use `apiFetch<T>()` — handles auth header, 401 redirect, and error parsing.
- **Types**: add shared API response shapes to `src/types/index.ts`.
- **State**: use Zustand stores for cross-component state; local `useState` for component-local state.
- **Routing**: pages live in `src/pages/`; add new routes in `App.tsx`.
- **Base URL**: never hardcode `/api` paths — `apiFetch` prepends the runtime base automatically.
