from app.platforms.base import PlatformConnector
from app.platforms.spotify import SpotifyConnector
from app.platforms.youtube import YouTubeConnector


class PlatformRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, PlatformConnector] = {
            "youtube": YouTubeConnector(),
            "spotify": SpotifyConnector(),
        }

    def get(self, name: str) -> PlatformConnector:
        connector = self._connectors.get(name)
        if not connector:
            raise KeyError(f"Unknown platform: {name}")
        return connector

    def all(self) -> list[str]:
        return sorted(self._connectors)
