from abc import ABC, abstractmethod
from dataclasses import dataclass


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
