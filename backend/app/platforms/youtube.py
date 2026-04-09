from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from app.platforms.base import PlatformConnector, PlaylistInfo, TrackInfo
from ytmusicapi import YTMusic


class YouTubeConnector(PlatformConnector):
    name = "youtube"
    auth_base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    token_url = "https://oauth2.googleapis.com/token"
    scope = "https://www.googleapis.com/auth/youtube.readonly"

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
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": self.scope,
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
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
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
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
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            data = response.json()
        credentials["access_token"] = data["access_token"]
        credentials["expires_at"] = int(datetime.now(UTC).timestamp()) + int(data.get("expires_in", 3600))
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
        if access_token:
            return await self._fetch_youtube_data_playlists(access_token)

        oauth_json = credentials.get("oauth_json")
        if not oauth_json:
            return []

        ytm = YTMusic(auth=oauth_json)
        library_playlists = ytm.get_library_playlists(limit=500)
        result: list[PlaylistInfo] = []
        for playlist in library_playlists:
            playlist_id = playlist.get("playlistId")
            if not playlist_id:
                continue
            details = ytm.get_playlist(playlist_id, limit=None)
            tracks = [
                TrackInfo(
                    source_id=item.get("videoId", ""),
                    title=item.get("title", "Unknown Title"),
                    artist=(item.get("artists") or [{"name": "Unknown Artist"}])[0]["name"],
                    album=(item.get("album") or {}).get("name", "Singles"),
                    duration_seconds=0,
                )
                for item in details.get("tracks", [])
                if item.get("videoId")
            ]
            result.append(PlaylistInfo(playlist_id=playlist_id, name=playlist["title"], tracks=tracks))
        return result

    async def search_track(self, query: str) -> TrackInfo | None:
        ytm = YTMusic()
        results = ytm.search(query, filter="songs", limit=1)
        if not results:
            return None
        first = results[0]
        source_id = first.get("videoId")
        if not source_id:
            return None
        return TrackInfo(
            source_id=source_id,
            title=first.get("title", query),
            artist=(first.get("artists") or [{"name": "Unknown Artist"}])[0]["name"],
            album=(first.get("album") or {}).get("name", "Singles"),
        )

    async def _fetch_youtube_data_playlists(self, access_token: str) -> list[PlaylistInfo]:
        headers = {"Authorization": f"Bearer {access_token}"}
        playlists: list[PlaylistInfo] = []
        next_page_token: str | None = None
        async with httpx.AsyncClient(timeout=20) as client:
            while True:
                params = {"part": "snippet,contentDetails", "mine": "true", "maxResults": 50}
                if next_page_token:
                    params["pageToken"] = next_page_token
                response = await client.get(
                    "https://www.googleapis.com/youtube/v3/playlists",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
                for item in payload.get("items", []):
                    playlist_id = item.get("id")
                    if not playlist_id:
                        continue
                    tracks = await self._fetch_playlist_items(client, headers, playlist_id)
                    playlists.append(
                        PlaylistInfo(
                            playlist_id=playlist_id,
                            name=(item.get("snippet") or {}).get("title", "Untitled"),
                            tracks=tracks,
                        )
                    )
                next_page_token = payload.get("nextPageToken")
                if not next_page_token:
                    break
        return playlists

    async def _fetch_playlist_items(
        self, client: httpx.AsyncClient, headers: dict[str, str], playlist_id: str
    ) -> list[TrackInfo]:
        tracks: list[TrackInfo] = []
        next_page_token: str | None = None
        while True:
            params = {"part": "snippet,contentDetails", "playlistId": playlist_id, "maxResults": 50}
            if next_page_token:
                params["pageToken"] = next_page_token
            response = await client.get(
                "https://www.googleapis.com/youtube/v3/playlistItems",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("items", []):
                snippet = item.get("snippet") or {}
                content = item.get("contentDetails") or {}
                video_id = content.get("videoId")
                if not video_id:
                    continue
                tracks.append(
                    TrackInfo(
                        source_id=video_id,
                        title=snippet.get("title", "Unknown Title"),
                        artist=snippet.get("videoOwnerChannelTitle", "Unknown Artist"),
                        album=(snippet.get("channelTitle") or "YouTube"),
                    )
                )
            next_page_token = payload.get("nextPageToken")
            if not next_page_token:
                break
        return tracks
