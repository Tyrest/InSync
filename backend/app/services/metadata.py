"""Audio metadata tagging (Ogg Opus primary; basic mutagen fallback for other formats)."""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen.flac import Picture
from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TXXX
from mutagen.mp3 import MP3
from mutagen.oggopus import OggOpus
from PIL import Image

log = logging.getLogger(__name__)

INSYNC_VERSION_KEY = "INSYNC_VERSION"
_DESC_MAX = 4000


def crop_thumbnail_to_square(path: Path) -> None:
    """Centre-crop *path* to a square in-place. No-op if already square or unreadable."""
    try:
        with Image.open(path) as img:
            w, h = img.size
            if w == h:
                return
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            cropped = img.crop((left, top, left + side, top + side))
            # Prefer the format Pillow detected; fall back to extension; then JPEG.
            ext_map = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
            fmt = img.format or ext_map.get(path.suffix.lower(), "JPEG")
            cropped.save(path, format=fmt)
            log.debug("Cropped thumbnail %s from %dx%d to %dx%d", path.name, w, h, side, side)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not crop thumbnail %s: %s", path, exc)


@dataclass(frozen=True, slots=True)
class AudioTagContext:
    """Fields used to write tags; ``ytdlp_extra`` is optional YouTube/yt-dlp-derived text fields."""

    title: str
    artist: str
    album: str
    insync_version: str
    ytdlp_extra: dict[str, str] | None = None
    thumbnail_path: Path | None = None


def _format_upload_date(raw: str) -> str | None:
    s = raw.strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def ytdlp_info_to_extra(info: dict[str, Any] | None) -> dict[str, str]:
    """Pick JSON-friendly string fields from a yt-dlp ``info_dict`` for tagging."""
    if not info:
        return {}
    extra: dict[str, str] = {}
    if vid := info.get("id"):
        extra["YOUTUBE_ID"] = str(vid)
    if url := info.get("webpage_url"):
        extra["URL"] = str(url)
    if uploader := info.get("uploader") or info.get("channel"):
        extra["UPLOADER"] = str(uploader)[:500]
    if ud := info.get("upload_date"):
        ds = _format_upload_date(str(ud))
        if ds:
            extra["DATE"] = ds
    if desc := info.get("description"):
        extra["DESCRIPTION"] = str(desc)[:_DESC_MAX]
    if dur := info.get("duration"):
        extra["DURATION"] = str(int(dur))
    return extra


def _mime_for_image(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    return "image/jpeg"


def _set_vorbis_picture(audio: OggOpus, thumbnail_path: Path) -> None:
    data = thumbnail_path.read_bytes()
    if not data:
        return
    picture = Picture()
    picture.type = 3
    picture.mime = _mime_for_image(thumbnail_path)
    picture.desc = "Cover"
    picture.data = data
    encoded = base64.b64encode(picture.write()).decode("ascii")
    audio["METADATA_BLOCK_PICTURE"] = encoded


def _apply_vorbis_text_tags(audio: OggOpus, ctx: AudioTagContext) -> None:
    audio["TITLE"] = ctx.title
    audio["ARTIST"] = ctx.artist
    audio["ALBUM"] = ctx.album
    audio[INSYNC_VERSION_KEY] = ctx.insync_version
    extra = ctx.ytdlp_extra or {}
    for k, v in extra.items():
        if not v:
            continue
        key = k.upper() if k.islower() else k
        audio[key] = v


def _tag_ogg_opus(path: Path, ctx: AudioTagContext) -> None:
    audio = OggOpus(path)
    _apply_vorbis_text_tags(audio, ctx)
    if ctx.thumbnail_path and ctx.thumbnail_path.is_file():
        try:
            _set_vorbis_picture(audio, ctx.thumbnail_path)
        except OSError as exc:
            log.warning("Could not embed thumbnail for %s: %s", path, exc)
    audio.save()


def _tag_mp3(path: Path, ctx: AudioTagContext) -> None:
    try:
        audio = MP3(path, ID3=ID3)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not open MP3 for tagging %s: %s", path, exc)
        return
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    assert tags is not None
    tags["TIT2"] = TIT2(encoding=3, text=ctx.title)
    tags["TPE1"] = TPE1(encoding=3, text=ctx.artist)
    tags["TALB"] = TALB(encoding=3, text=ctx.album)
    keep_txxx = [f for f in tags.getall("TXXX") if getattr(f, "desc", "") != INSYNC_VERSION_KEY]
    tags.setall(
        "TXXX",
        keep_txxx + [TXXX(encoding=3, desc=INSYNC_VERSION_KEY, text=ctx.insync_version)],
    )
    if ctx.thumbnail_path and ctx.thumbnail_path.is_file():
        try:
            data = ctx.thumbnail_path.read_bytes()
            mime = _mime_for_image(ctx.thumbnail_path)
            tags.delall("APIC")
            tags.add(
                APIC(
                    encoding=3,
                    mime=mime,
                    type=3,
                    desc="Cover",
                    data=data,
                )
            )
        except OSError as exc:
            log.warning("Could not embed MP3 thumbnail for %s: %s", path, exc)
    audio.save()


def _tag_mutagen_easy(path: Path, ctx: AudioTagContext) -> None:
    audio = MutagenFile(path, easy=True)
    if audio is None:
        log.warning("Unsupported or unreadable audio file for tagging: %s", path)
        return
    audio["title"] = ctx.title
    audio["artist"] = ctx.artist
    audio["album"] = ctx.album
    audio[INSYNC_VERSION_KEY.lower()] = ctx.insync_version
    extra = ctx.ytdlp_extra or {}
    for k, v in extra.items():
        if v:
            audio[k.lower()] = v[:_DESC_MAX]
    audio.save()


def tag_audio_file(file_path: Path, ctx: AudioTagContext) -> None:
    if not file_path.is_file():
        return
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".opus":
            _tag_ogg_opus(file_path, ctx)
        elif suffix == ".mp3":
            _tag_mp3(file_path, ctx)
        else:
            _tag_mutagen_easy(file_path, ctx)
    except Exception as exc:  # noqa: BLE001
        log.warning("Tagging failed for %s: %s", file_path, exc)
