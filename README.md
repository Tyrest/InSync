# InSync

Self-hosted bridge that syncs YouTube Music / Spotify playlists into Jellyfin.

## Features

- Jellyfin-based authentication (no separate passwords stored)
- First logged-in user becomes app admin
- Sync playlists from YouTube and Spotify
- Spotify playlists map to downloadable sources via yt-dlp flow
- Async concurrent downloads with configurable concurrency
- Daily scheduled sync + manual sync trigger
- Per-user playlist sync mapping in Jellyfin
- Supports reverse proxy sub-paths via `BASE_URL`

## Quick Start

```bash
cd backend
uv lock
uv sync
uv run ruff check
uv run ty check
uv run uvicorn app.main:app --reload
```

In a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

## Docker

Pull the pre-built image from GHCR:

```bash
docker pull ghcr.io/tyrest/insync:latest
```

Or build locally:

```bash
docker build -t insync .
docker run -d \
  -p 8090:8080 \
  -e BASE_URL=/ \
  -v ./insync-data:/data \
  -v ./jellyfin-music:/music \
  insync
```

Mount `./jellyfin-music` into Jellyfin as a music library path too.

### Persisting Jellyfin URL and API key across rebuilds

1. **Bind mount `/data`** (required for SQLite). The image sets `DATA_DIR=/data`, so the database (including values saved in the Setup wizard) lives on the host:

   ```bash
   -v ./insync-data:/data
   ```

   Rebuilding the image does **not** remove that folder; only removing the volume or the host directory loses settings.

2. **Optional: environment variables** — If `/data` is empty (first run) but you set both:

   - `JELLYFIN_URL` — e.g. `http://ty-tpad/media` or `https://jellyfin.example.com`
   - `JELLYFIN_API_KEY` — your Jellyfin API key

   the app writes them into the database on startup so you can skip the Setup wizard. If the database already has Jellyfin rows (e.g. from a previous wizard save on a persisted volume), env vars are **not** overwritten.

### `BASE_URL` for reverse-proxy subpaths

The same published image supports both root and subpath deployments at runtime (no rebuild required).

- Root deploy: `BASE_URL=/`
- Subpath deploy: `BASE_URL=/insync`

Example:

```bash
docker run -d \
  -p 8090:8080 \
  -e BASE_URL=/insync \
  -v ./insync-data:/data \
  -v ./jellyfin-music:/music \
  insync
```

If you run behind a reverse proxy, make sure requests under `/insync` are forwarded to this container.
InSync accepts both direct `/api` + `/assets` paths and `/insync/api` + `/insync/assets` when `BASE_URL=/insync`.

### JWT behavior (zero-config)

- On startup, InSync resolves JWT signing secret in this order:
  1. `jwt_secret` already stored in app DB (`/data/music_sync.sqlite3`)
  2. `JWT_SECRET` environment variable (if provided)
  3. auto-generated random secret
- If no DB value exists yet, InSync persists the resolved secret into the DB so restarts keep sessions stable.
- If you delete `/data` (or use a fresh empty volume), a new JWT secret is generated and existing sessions become invalid.

### Sensitive settings storage

Admin-configured secrets are stored in plaintext in the app SQLite database under `/data/music_sync.sqlite3` (for example: Jellyfin API key, OAuth client secrets, webhook secret, and JWT secret).

Recommended safeguards for self-hosting:

- Restrict host filesystem permissions on the mounted `/data` directory.
- Use encrypted disk/volume storage where possible.
- Treat backups containing `/data` as sensitive material.
