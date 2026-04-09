import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yt_dlp
from app.services.metadata import tag_audio_file
from yt_dlp.utils import DownloadError

log = logging.getLogger(__name__)


@dataclass(slots=True)
class AudioConfig:
    format: str = "mp3"
    quality: str = "320"


@dataclass(slots=True)
class DownloadRequest:
    source_id: str
    search_query: str
    title: str
    artist: str
    album: str = "Singles"


@dataclass(slots=True)
class DownloadResult:
    request: DownloadRequest
    path: Path | None
    error: str | None = None


def _safe_name(value: str) -> str:
    return value.replace("/", "_").replace("\x00", "_")


def _safe_source_id_fragment(source_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", source_id).strip("_")
    return (cleaned or "unknown")[:120]


_YOUTUBE_VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def _yt_dlp_search_or_url_argument(query: str) -> str:
    """Force plain text queries through YouTube search so titles like ``CS:GO`` are not parsed as URL schemes."""
    q = query.strip()
    if not q:
        return q
    low = q.lower()
    if low.startswith(("http://", "https://")):
        return q
    if low.startswith("ytsearch"):
        return q
    return f"ytsearch1:{q}"


def _yt_dlp_input_for_request(request: DownloadRequest) -> str:
    """Prefer a direct watch URL when ``source_id`` is a YouTube video id; otherwise search by title/artist."""
    sid = request.source_id.strip()
    if _YOUTUBE_VIDEO_ID_RE.fullmatch(sid):
        return f"https://www.youtube.com/watch?v={sid}"
    return _yt_dlp_search_or_url_argument(request.search_query)


class DownloadService:
    def __init__(self, music_dir: Path, concurrency: int, audio_config: AudioConfig | None = None) -> None:
        self.music_dir = music_dir
        self._concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        self.audio_config = audio_config or AudioConfig()

    # --- path helpers (flat layout: music_dir / artist / file) ---

    def _mp3_path(self, filename_stem: str, artist: str) -> Path:
        ext = self.audio_config.format if self.audio_config.format != "best" else "mp3"
        return self.music_dir / _safe_name(artist) / f"{filename_stem}.{ext}"

    def unique_mp3_path(self, title: str, artist: str, _album: str, source_id: str) -> Path:
        frag = _safe_source_id_fragment(source_id)
        return self._mp3_path(f"{_safe_name(title)}__{frag}", artist)

    def legacy_mp3_path(self, title: str, artist: str, album: str) -> Path:
        """Historical 3-level layout: ``music_dir / artist / album / title.mp3``."""
        return self.music_dir / _safe_name(artist) / _safe_name(album) / f"{_safe_name(title)}.mp3"

    def flat_legacy_mp3_path(self, title: str, artist: str) -> Path:
        """Flat 2-level layout without source_id (transitional)."""
        return self.music_dir / _safe_name(artist) / f"{_safe_name(title)}.mp3"

    def expected_mp3_path(self, title: str, artist: str, album: str) -> Path:
        return self.legacy_mp3_path(title, artist, album)

    def first_existing_audio_path(self, title: str, artist: str, album: str, source_id: str) -> Path | None:
        """Return an on-disk file for this track, checking new flat layout first, then legacy 3-level."""
        candidates = [
            self.unique_mp3_path(title, artist, album, source_id),
            self.flat_legacy_mp3_path(title, artist),
            self.legacy_mp3_path(title, artist, album),
        ]
        for path in candidates:
            if path.is_file():
                return path
        return None

    @staticmethod
    def path_key_variants(path: Path) -> list[str]:
        return list({str(path), str(path.resolve())})

    # --- download orchestration ---

    async def download_many(
        self,
        items: list[tuple[DownloadRequest, int]],
        on_downloading: Callable[[int], None] | None = None,
        on_each_result: Callable[[int, DownloadResult], Awaitable[None]] | None = None,
    ) -> list[DownloadResult]:
        async def run_indexed(index: int, req: DownloadRequest, task_id: int) -> tuple[int, DownloadResult]:
            result = await self._download(req, task_id, on_downloading)
            return index, result

        n = len(items)
        if n == 0:
            return []
        log.info("Starting download batch: %s item(s), concurrency=%s", n, self._concurrency)
        tasks = [asyncio.create_task(run_indexed(i, req, task_id)) for i, (req, task_id) in enumerate(items)]
        ordered: list[DownloadResult | None] = [None] * n
        for finished in asyncio.as_completed(tasks):
            index, result = await finished
            ordered[index] = result
            if on_each_result is not None:
                await on_each_result(index, result)
        assert all(r is not None for r in ordered)
        log.info("Download batch finished: %s item(s)", n)
        return cast(list[DownloadResult], ordered)

    async def _download(
        self,
        request: DownloadRequest,
        task_id: int,
        on_downloading: Callable[[int], None] | None,
    ) -> DownloadResult:
        async with self._semaphore:
            if on_downloading is not None:
                await asyncio.to_thread(on_downloading, task_id)
            log.info("yt-dlp starting task_id=%s: %s — %s", task_id, request.artist, request.title)
            try:
                path = await asyncio.to_thread(self._run_download, request)
                log.info("yt-dlp finished task_id=%s: %s — %s", task_id, request.artist, request.title)
                return DownloadResult(request=request, path=path, error=None)
            except DownloadError as exc:
                err = self._friendly_ytdlp_error(exc)
                log.warning("yt-dlp failed task_id=%s: %s — %s | %s", task_id, request.artist, request.title, err[:300])
                return DownloadResult(request=request, path=None, error=err)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "yt-dlp failed task_id=%s: %s — %s | %s",
                    task_id,
                    request.artist,
                    request.title,
                    str(exc)[:300],
                )
                return DownloadResult(request=request, path=None, error=str(exc))

    @staticmethod
    def _friendly_ytdlp_error(exc: DownloadError) -> str:
        raw = str(exc)
        lower = raw.lower()
        if "private video" in lower or "is private" in lower:
            return f"This YouTube video is private or requires sign-in; it cannot be downloaded. Raw: {raw}"
        if any(
            phrase in lower
            for phrase in (
                "video unavailable",
                "deleted video",
                "removed",
                "no longer available",
                "copyright",
                "blocked",
                "not available",
                "members only",
                "join this channel",
            )
        ):
            return (
                "This YouTube video is unavailable (removed, private, region-blocked, members-only, "
                f"or similar). Raw: {raw}"
            )
        if "2087" in raw or "video unavailable" in lower:
            return (
                "YouTube reported this video as unavailable (often error 2087): the upload may be "
                "region-blocked, age- or members-only, removed, or temporarily blocked for automated access. "
                "Try updating yt-dlp; some tracks cannot be downloaded. Raw: " + raw
            )
        return raw

    def _run_download(self, request: DownloadRequest) -> Path:
        path = self.unique_mp3_path(request.title, request.artist, request.album, request.source_id)
        artist_dir = path.parent
        artist_dir.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            tag_audio_file(path, request.title, request.artist, request.album)
            return path
        output_template = str(artist_dir / f"{path.stem}.%(ext)s")
        ac = self.audio_config
        options: dict = {
            "quiet": True,
            "noprogress": True,
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "default_search": "ytsearch1",
            "js_runtimes": {"deno": {}},
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": ac.format if ac.format != "best" else "mp3",
                    "preferredquality": ac.quality,
                }
            ],
        }
        inp = _yt_dlp_input_for_request(request)
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([inp])
        if not path.is_file():
            raise RuntimeError(f"Download produced no file for: {inp}")
        tag_audio_file(path, request.title, request.artist, request.album)
        return path
