from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
import spotipy
from app.platforms.base import PlatformConnector, PlaylistInfo, TrackInfo


class SpotifyConnector(PlatformConnector):
    name = "spotify"
    auth_base_url = "https://accounts.spotify.com/authorize"
    token_url = "https://accounts.spotify.com/api/token"
    scopes = [
        "playlist-read-private",
        "playlist-read-collaborative",
        "user-library-read",
    ]

    async def start_auth(
        self,
        *,
        user_id: int,
        redirect_uri: str,
        state: str,
        client_id: str,
    ) -> dict:
        _ = user_id
        query = urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": " ".join(self.scopes),
                "state": state,
            }
        )
        return {"authorize_url": f"{self.auth_base_url}?{query}"}

    async def complete_auth(
        self,
        *,
        user_id: int,
        callback_data: dict,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> dict:
        _ = (user_id, code_verifier)
        code = callback_data.get("code")
        if not code:
            raise ValueError("Missing OAuth code")
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data = response.json()
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token"),
            "expires_at": int(datetime.now(UTC).timestamp()) + int(data.get("expires_in", 3600)),
            "token_type": data.get("token_type", "Bearer"),
        }

    async def refresh_credentials(
        self,
        *,
        credentials: dict,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> dict:
        access_token = credentials.get("access_token")
        expires_at = int(credentials.get("expires_at", 0))
        if access_token and expires_at > int(datetime.now(UTC).timestamp()) + 60:
            return credentials

        refresh_token = credentials.get("refresh_token")
        if not refresh_token or not client_id or not client_secret:
            return credentials

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                self.token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data = response.json()
        credentials["access_token"] = data["access_token"]
        credentials["expires_at"] = int(datetime.now(UTC).timestamp()) + int(data.get("expires_in", 3600))
        if data.get("refresh_token"):
            credentials["refresh_token"] = data["refresh_token"]
        return credentials

    async def fetch_playlists(self, credentials: dict) -> list[PlaylistInfo]:
        if "mock_playlists" in credentials:
            playlists: list[PlaylistInfo] = []
            for raw in credentials["mock_playlists"]:
                tracks = [
                    TrackInfo(
                        source_id=track["source_id"],
                        title=track["title"],
                        artist=track.get("artist", "Unknown Artist"),
                        album=track.get("album", "Singles"),
                        isrc=track.get("isrc"),
                    )
                    for track in raw.get("tracks", [])
                ]
                playlists.append(
                    PlaylistInfo(
                        playlist_id=raw["playlist_id"],
                        name=raw["name"],
                        tracks=tracks,
                    )
                )
            return playlists

        access_token = credentials.get("access_token")
        if not access_token:
            return []

        client = spotipy.Spotify(auth=access_token)
        playlists_resp = client.current_user_playlists(limit=50)
        result: list[PlaylistInfo] = []
        for item in playlists_resp.get("items", []):
            playlist_id = item["id"]
            playlist_name = item["name"]
            tracks_resp = client.playlist_items(playlist_id, additional_types=("track",), limit=100)
            tracks: list[TrackInfo] = []
            for row in tracks_resp.get("items", []):
                track = row.get("track") or {}
                ext_ids = track.get("external_ids") or {}
                artists = track.get("artists") or [{"name": "Unknown Artist"}]
                tracks.append(
                    TrackInfo(
                        source_id=track.get("id") or "",
                        title=track.get("name") or "Unknown Title",
                        artist=artists[0].get("name", "Unknown Artist"),
                        album=(track.get("album") or {}).get("name", "Singles"),
                        duration_seconds=int(track.get("duration_ms", 0) / 1000),
                        isrc=ext_ids.get("isrc"),
                    )
                )
            result.append(PlaylistInfo(playlist_id=playlist_id, name=playlist_name, tracks=tracks))
        return result

    async def search_track(self, query: str) -> TrackInfo | None:
        return None
