"""Tests for audio tagging helpers."""

import base64
import shutil
import subprocess
from pathlib import Path

import pytest
from app.services.metadata import (
    INSYNC_VERSION_KEY,
    AudioTagContext,
    tag_audio_file,
    ytdlp_info_to_extra,
)
from app.version import get_app_version
from mutagen.flac import Picture
from mutagen.oggopus import OggOpus


def test_ytdlp_info_to_extra_maps_fields() -> None:
    info = {
        "id": "abc123",
        "webpage_url": "https://www.youtube.com/watch?v=abc123",
        "uploader": "Channel Name",
        "upload_date": "20240115",
        "description": "Hello world",
        "duration": 120,
    }
    extra = ytdlp_info_to_extra(info)
    assert extra["YOUTUBE_ID"] == "abc123"
    assert "youtube.com" in extra["URL"]
    assert extra["UPLOADER"] == "Channel Name"
    assert extra["DATE"] == "2024-01-15"
    assert "Hello" in extra["DESCRIPTION"]
    assert extra["DURATION"] == "120"


@pytest.fixture
def ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")


@pytest.mark.usefixtures("ffmpeg_available")
def test_tag_opus_embeds_version_and_reads_back(tmp_path: Path) -> None:
    opus_path = tmp_path / "t.opus"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-t",
            "0.1",
            "-c:a",
            "libopus",
            str(opus_path),
        ],
        check=True,
        capture_output=True,
    )
    ver = get_app_version()
    ctx = AudioTagContext(
        title="Test Title",
        artist="Test Artist",
        album="Test Album",
        insync_version=ver,
        ytdlp_extra=ytdlp_info_to_extra(
            {"id": "x", "webpage_url": "https://youtu.be/x", "upload_date": "20200101", "description": "d"}
        ),
    )
    tag_audio_file(opus_path, ctx)
    audio = OggOpus(opus_path)
    assert audio.get("TITLE", [""])[0] == "Test Title"
    assert audio.get(INSYNC_VERSION_KEY, [""])[0] == ver
    assert audio.get("YOUTUBE_ID", [""])[0] == "x"


@pytest.mark.usefixtures("ffmpeg_available")
def test_tag_opus_embeds_thumbnail(tmp_path: Path) -> None:
    opus_path = tmp_path / "t.opus"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-t",
            "0.1",
            "-c:a",
            "libopus",
            str(opus_path),
        ],
        check=True,
        capture_output=True,
    )
    # 1x1 JPEG
    jpg = tmp_path / "thumb.jpg"
    jpg.write_bytes(
        base64.b64decode(
            "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
            "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCwAA8A/9k="
        )
    )
    ctx = AudioTagContext(
        title="T",
        artist="A",
        album="Al",
        insync_version="9.9.9-test",
        thumbnail_path=jpg,
    )
    tag_audio_file(opus_path, ctx)
    audio = OggOpus(opus_path)
    raw = audio.get("METADATA_BLOCK_PICTURE", [""])[0]
    assert raw
    data = base64.b64decode(raw)
    pic = Picture(data)
    assert len(pic.data) > 0
