import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yt_dlp
from app.services.metadata import AudioTagContext, crop_thumbnail_to_square, tag_audio_file, ytdlp_info_to_extra
from app.version import get_app_version
from yt_dlp.utils import DownloadError

log = logging.getLogger(__name__)


@dataclass(slots=True)
class AudioConfig:
    format: str = "opus"
    quality: str = "128"


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


def _output_extension(audio_format: str) -> str:
    if audio_format == "best":
        return "opus"
    return audio_format


def _ytdlp_format_selector_for_extension(ext: str) -> str:
    if ext == "opus":
        return "bestaudio[acodec=opus]/bestaudio[ext=m4a]/bestaudio/best"
    return "bestaudio/best"


class DownloadService:
    def __init__(self, music_dir: Path, concurrency: int, audio_config: AudioConfig | None = None) -> None:
        self.music_dir = music_dir
        self._concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        self.audio_config = audio_config or AudioConfig()

    # --- path helpers (flat layout: music_dir / artist / file) ---

    def _audio_output_path(self, filename_stem: str, artist: str) -> Path:
        ext = _output_extension(self.audio_config.format)
        return self.music_dir / _safe_name(artist) / f"{filename_stem}.{ext}"

    def unique_audio_path(self, title: str, artist: str, _album: str, source_id: str) -> Path:
        frag = _safe_source_id_fragment(source_id)
        return self._audio_output_path(f"{_safe_name(title)}__{frag}", artist)

    def first_existing_audio_path(self, title: str, artist: str, album: str, source_id: str) -> Path | None:
        """Return an on-disk file for this track, checking new flat layout first, then legacy paths."""
        candidates = [
            self.unique_audio_path(title, artist, album, source_id),
            # flat legacy: music_dir / artist / title.mp3
            self.music_dir / _safe_name(artist) / f"{_safe_name(title)}.mp3",
            # 3-level legacy: music_dir / artist / album / title.mp3
            self.music_dir / _safe_name(artist) / _safe_name(album) / f"{_safe_name(title)}.mp3",
        ]
        for path in candidates:
            if path.is_file():
                return path
        return None

    @staticmethod
    def path_key_variants(path: Path) -> list[str]:
        return list({str(path), str(path.resolve())})

    @staticmethod
    def _find_sidecar_thumbnail(artist_dir: Path, stem: str) -> Path | None:
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            p = artist_dir / f"{stem}{ext}"
            if p.is_file():
                return p
        for p in sorted(artist_dir.glob(f"{stem}.*")):
            if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and p.is_file():
                return p
        return None

    def _ytdlp_options(self, output_template: str, out_path: Path) -> dict[str, Any]:
        ac = self.audio_config
        ext = out_path.suffix.lstrip(".").lower()
        return {
            "quiet": True,
            "noprogress": True,
            "format": _ytdlp_format_selector_for_extension(ext),
            "outtmpl": output_template,
            "default_search": "ytsearch1",
            "js_runtimes": {"deno": {}},
            "writethumbnail": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": ext,
                    "preferredquality": ac.quality,
                }
            ],
        }

    # --- download orchestration ---

    async def download_many(
        self,
        items: list[tuple[DownloadRequest, int]],
        on_downloading: Callable[[int], Awaitable[None]] | None = None,
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
        on_downloading: Callable[[int], Awaitable[None]] | None,
    ) -> DownloadResult:
        async with self._semaphore:
            if on_downloading is not None:
                await on_downloading(task_id)
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

    def _tag_from_request_only(self, path: Path, request: DownloadRequest) -> None:
        ctx = AudioTagContext(
            title=request.title,
            artist=request.artist,
            album=request.album,
            insync_version=get_app_version(),
        )
        tag_audio_file(path, ctx)

    def _tag_after_download(
        self,
        path: Path,
        request: DownloadRequest,
        artist_dir: Path,
        info: dict[str, Any] | None,
    ) -> None:
        stem = path.stem
        thumb = self._find_sidecar_thumbnail(artist_dir, stem)
        if thumb is not None:
            crop_thumbnail_to_square(thumb)
        extra = ytdlp_info_to_extra(info) if info else {}
        ctx = AudioTagContext(
            title=request.title,
            artist=request.artist,
            album=request.album,
            insync_version=get_app_version(),
            ytdlp_extra=extra or None,
            thumbnail_path=thumb,
        )
        tag_audio_file(path, ctx)
        if thumb is not None and thumb.is_file():
            try:
                thumb.unlink()
            except OSError as exc:
                log.debug("Could not remove thumbnail sidecar %s: %s", thumb, exc)

    def _run_download(self, request: DownloadRequest) -> Path:
        path = self.unique_audio_path(request.title, request.artist, request.album, request.source_id)
        artist_dir = path.parent
        artist_dir.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            self._tag_from_request_only(path, request)
            return path
        output_template = str(artist_dir / f"{path.stem}.%(ext)s")
        options = self._ytdlp_options(output_template, path)
        inp = _yt_dlp_input_for_request(request)
        info: dict[str, Any] | None = None
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(inp, download=True)
        if not path.is_file():
            raise RuntimeError(f"Download produced no file for: {inp}")
        self._tag_after_download(path, request, artist_dir, info)
        return path
