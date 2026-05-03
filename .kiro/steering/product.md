# InSync — Product Overview

InSync is a self-hosted service that bridges music streaming platforms (YouTube Music, Spotify) with a personal Jellyfin media server. It syncs playlists from those platforms, downloads the audio via yt-dlp, and keeps the corresponding Jellyfin playlists up to date.

## Core Capabilities

- **Jellyfin-native auth** — no separate user accounts; login delegates to Jellyfin credentials. First user to log in becomes admin.
- **Platform linking** — users connect YouTube Music and/or Spotify accounts via OAuth.
- **Playlist sync** — maps platform playlists to Jellyfin playlists; downloads missing tracks automatically.
- **Scheduled + manual sync** — daily background sync (configurable UTC hour) plus on-demand trigger.
- **Async downloads** — concurrent yt-dlp downloads with configurable concurrency limit.
- **Reverse-proxy support** — runtime `BASE_URL` env var enables subpath deployments without rebuilding.
- **Zero-config JWT** — secret resolved from DB → env var → auto-generated; persisted on first run.

## Deployment

- Docker Compose (recommended): InSync on port 8090, Jellyfin on port 8096, shared music volume.
- Standalone Docker: single container, mount `/data` (SQLite) and `/music` (audio files).
- Local dev: FastAPI backend + Vite frontend run separately.

## Users

Self-hosters who want their streaming platform playlists available offline in Jellyfin.
