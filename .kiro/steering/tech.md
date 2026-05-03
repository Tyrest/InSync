# Tech Stack

## Backend

- **Language**: Python 3.13+
- **Framework**: FastAPI with async route handlers
- **ORM**: SQLAlchemy 2.x (mapped_column / Mapped style), Alembic for migrations
- **Database**: SQLite (WAL mode, `music_sync.sqlite3`) — default, configurable via `DATABASE_URL`
- **Settings**: pydantic-settings (`Settings` class in `app/config.py`), loaded from env / `.env` file, cached with `@lru_cache`
- **Auth**: JWT via PyJWT (`HS256`), Jellyfin credential delegation
- **Scheduler**: APScheduler (daily sync job)
- **Downloads**: yt-dlp + yt-dlp-ejs for audio; mutagen + Pillow for metadata/artwork
- **HTTP client**: httpx (async)
- **Spotify**: spotipy; **YouTube Music**: ytmusicapi
- **Package manager**: [uv](https://docs.astral.sh/uv/) — use `uv run` for all backend commands
- **Linter**: Ruff (`line-length = 120`, rules: E, F, I, UP, SIM)
- **Type checker**: ty

## Frontend

- **Language**: TypeScript (strict)
- **Framework**: React 18 with React Router v6
- **State**: Zustand
- **Build tool**: Vite 5
- **Styling**: Tailwind CSS v3 + PostCSS
- **API calls**: custom `apiFetch` wrapper in `src/api/client.ts` (Bearer token, auto-redirect on 401)
- **Package manager**: npm

## Infrastructure

- Docker / Docker Compose
- Single `Dockerfile` builds backend + copies frontend `dist/` into `backend/static/`
- FastAPI serves the SPA from `backend/static/` and rewrites `/__INSYNC_BASE__/` placeholder at runtime

---

## Common Commands

### Backend (run from `backend/`)

```bash
uv sync                          # install dependencies
uv run uvicorn app.main:app --reload   # dev server (port 8080)
uv run ruff format               # format
uv run ruff check                # lint
uv run ruff check --fix          # lint + auto-fix
uv run ty check                  # type check
uv run pytest                    # run tests

# Run lint + type check in parallel (faster CI)
uv run ruff format & uv run ruff check & uv run ty check & wait
```

### Frontend (run from `frontend/`)

```bash
npm install       # install dependencies
npm run dev       # dev server (port 5173, proxies /api to backend)
npm run build     # production build → dist/
npm run preview   # preview production build
```

### Docker

```bash
docker compose up -d             # start InSync + Jellyfin
docker compose down              # stop
docker build -t insync .         # build image locally
```

### Database migrations (run from `backend/`)

```bash
uv run alembic upgrade head      # apply migrations
uv run alembic revision --autogenerate -m "description"  # generate migration
```
