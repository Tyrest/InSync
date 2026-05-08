import json
import logging
import re
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

_YOUTUBE_VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")


@dataclass(frozen=True, slots=True)
class SponsorSegment:
    start: float  # seconds
    end: float  # seconds
    category: str


class SponsorBlockClient:
    BASE_URL = "https://sponsor.ajay.app/api/skipSegments"
    TIMEOUT = 10.0  # seconds

    def __init__(self, categories: list[str]) -> None:
        """categories: list of SponsorBlock category strings to request."""
        self._categories = categories

    async def get_segments(self, video_id: str) -> list[SponsorSegment]:
        """Query the SponsorBlock API for the given YouTube video ID.

        Returns an empty list if:
        - video_id is not a valid YouTube video ID (11-char alphanumeric)
        - API returns 404 (no community data)
        - API returns any other HTTP error (logs warning)
        - Request times out (logs warning)
        """
        if not _YOUTUBE_VIDEO_ID_RE.match(video_id):
            return []

        params = {
            "videoID": video_id,
            "categories": json.dumps(self._categories),
        }

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                response = await client.get(self.BASE_URL, params=params)

            if response.status_code == 200:
                data = response.json()
                return [
                    SponsorSegment(
                        start=float(item["segment"][0]),
                        end=float(item["segment"][1]),
                        category=item["category"],
                    )
                    for item in data
                ]

            if response.status_code == 404:
                log.debug("SponsorBlock: no segments found for video_id=%s", video_id)
                return []

            log.warning(
                "SponsorBlock: unexpected HTTP %d for video_id=%s",
                response.status_code,
                video_id,
            )
            return []

        except httpx.TimeoutException:
            log.warning("SponsorBlock: request timed out for video_id=%s", video_id)
            return []

        except Exception as exc:  # noqa: BLE001
            log.warning("SponsorBlock: error fetching segments for video_id=%s: %s", video_id, exc)
            return []
