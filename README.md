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
