from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass(slots=True)
class TrackInfo:
    source_id: str
    title: str
    artist: str
    album: str = "Singles"
    duration_seconds: int = 0
    isrc: str | None = None


@dataclass(slots=True)
class PlaylistInfo:
    playlist_id: str
    name: str
    tracks: list[TrackInfo]


def _load_mock_playlists(credentials: dict) -> list[PlaylistInfo]:
    """Load mock playlists from credentials dict for testing.
    
    Used by platform connectors when 'mock_playlists' key exists in credentials.
    """
    if "mock_playlists" not in credentials:
        return []
    
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


class PlatformConnector(ABC):
    name: str

    @abstractmethod
    async def start_auth(
        self,
        *,
        user_id: int,
        redirect_uri: str,
        state: str,
        client_id: str,
    ) -> dict: ...

    @abstractmethod
    async def complete_auth(
        self,
        *,
        user_id: int,
        callback_data: dict,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> dict: ...

    async def refresh_credentials(
        self,
        *,
        credentials: dict,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> dict:
        return credentials

    @abstractmethod
    async def fetch_playlists(self, credentials: dict) -> list[PlaylistInfo]: ...

    @abstractmethod
    async def search_track(self, query: str) -> TrackInfo | None: ...

    @abstractmethod
    def get_credentials(self, db: Session) -> tuple[str | None, str | None]: ...
