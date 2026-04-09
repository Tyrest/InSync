"""Tests for download URL selection and path helpers."""

from pathlib import Path

from app.services.download import (
    AudioConfig,
    DownloadRequest,
    DownloadService,
    _safe_name,
    _safe_source_id_fragment,
    _yt_dlp_input_for_request,
    _yt_dlp_search_or_url_argument,
)


def test_youtube_video_id_uses_direct_url() -> None:
    req = DownloadRequest(
        source_id="dQw4w9WgXcQ",
        search_query="Rick Astley Never Gonna Give You Up",
        title="Never Gonna Give You Up",
        artist="Rick Astley",
    )
    assert _yt_dlp_input_for_request(req) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_non_youtube_id_falls_back_to_search() -> None:
    req = DownloadRequest(
        source_id="spotify:track:abc123def456",
        search_query="Some Song Some Artist",
        title="Some Song",
        artist="Some Artist",
    )
    result = _yt_dlp_input_for_request(req)
    assert result.startswith("ytsearch1:")
    assert "Some Song Some Artist" in result


def test_colon_in_query_uses_ytsearch() -> None:
    result = _yt_dlp_search_or_url_argument("CS:GO - Clutch Script for Beginners MrMaxim")
    assert result.startswith("ytsearch1:")
    assert "CS:GO" in result


def test_http_url_passed_through() -> None:
    url = "https://www.youtube.com/watch?v=abcdefghijk"
    assert _yt_dlp_search_or_url_argument(url) == url


def test_safe_name_replaces_slashes() -> None:
    assert _safe_name("AC/DC") == "AC_DC"
    assert _safe_name("normal") == "normal"


def test_safe_source_id_fragment() -> None:
    assert _safe_source_id_fragment("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert _safe_source_id_fragment("weird!!chars##") == "weird_chars"
    assert _safe_source_id_fragment("") == "unknown"


def test_unique_path_is_flat_layout(tmp_path: Path) -> None:
    ds = DownloadService(tmp_path, concurrency=1)
    p = ds.unique_mp3_path("My Song", "My Artist", "My Album", "dQw4w9WgXcQ")
    # Flat layout: music_dir / artist / file (no album directory)
    assert p.parent == tmp_path / "My Artist"
    assert p.name == "My Song__dQw4w9WgXcQ.mp3"


def test_legacy_path_has_album_dir(tmp_path: Path) -> None:
    ds = DownloadService(tmp_path, concurrency=1)
    p = ds.legacy_mp3_path("My Song", "My Artist", "My Album")
    assert p.parent == tmp_path / "My Artist" / "My Album"
    assert p.name == "My Song.mp3"


def test_first_existing_prefers_unique(tmp_path: Path) -> None:
    ds = DownloadService(tmp_path, concurrency=1)
    unique = ds.unique_mp3_path("Song", "Artist", "Album", "abcdefghijk")
    unique.parent.mkdir(parents=True, exist_ok=True)
    unique.write_text("audio data")
    legacy = ds.legacy_mp3_path("Song", "Artist", "Album")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("old audio data")

    found = ds.first_existing_audio_path("Song", "Artist", "Album", "abcdefghijk")
    assert found == unique


def test_audio_config_affects_extension(tmp_path: Path) -> None:
    ds = DownloadService(tmp_path, concurrency=1, audio_config=AudioConfig(format="flac", quality="0"))
    p = ds.unique_mp3_path("Song", "Artist", "Album", "abcdefghijk")
    assert p.suffix == ".flac"
