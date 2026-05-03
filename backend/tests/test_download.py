"""Tests for download URL selection and path helpers."""

import tempfile
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
from hypothesis import given, settings
from hypothesis import strategies as st


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
    p = ds.unique_audio_path("My Song", "My Artist", "My Album", "dQw4w9WgXcQ")
    # Flat layout: music_dir / artist / file (no album directory)
    assert p.parent == tmp_path / "My Artist"
    assert p.name == "My Song__dQw4w9WgXcQ.opus"


def test_legacy_3level_path_found_by_first_existing(tmp_path: Path) -> None:
    """first_existing_audio_path still finds 3-level legacy files (music_dir/artist/album/title.mp3)."""
    ds = DownloadService(tmp_path, concurrency=1)
    legacy = tmp_path / "My Artist" / "My Album" / "My Song.mp3"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("old audio data")

    found = ds.first_existing_audio_path("My Song", "My Artist", "My Album", "abcdefghijk")
    assert found == legacy


def test_first_existing_prefers_unique(tmp_path: Path) -> None:
    ds = DownloadService(tmp_path, concurrency=1)
    unique = ds.unique_audio_path("Song", "Artist", "Album", "abcdefghijk")
    unique.parent.mkdir(parents=True, exist_ok=True)
    unique.write_text("audio data")
    # 3-level legacy path
    legacy = tmp_path / "Artist" / "Album" / "Song.mp3"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("old audio data")

    found = ds.first_existing_audio_path("Song", "Artist", "Album", "abcdefghijk")
    assert found == unique


def test_audio_config_affects_extension(tmp_path: Path) -> None:
    ds = DownloadService(tmp_path, concurrency=1, audio_config=AudioConfig(format="flac", quality="0"))
    p = ds.unique_audio_path("Song", "Artist", "Album", "abcdefghijk")
    assert p.suffix == ".flac"


def test_ytdlp_format_prefers_opus_when_output_is_opus() -> None:
    ds = DownloadService(Path("/tmp"), concurrency=1)
    opts = ds._ytdlp_options("/tmp/stem.%(ext)s", Path("/tmp/stem.opus"))
    assert opts["format"] == "bestaudio[acodec=opus]/bestaudio[ext=m4a]/bestaudio/best"
    assert opts["writethumbnail"] is True


# Feature: backend-refactor, Property 6
# Validates: Requirements 6.2, 6.3
@given(st.frozensets(st.integers(min_value=0, max_value=2)))
@settings(max_examples=50)
def test_first_existing_audio_path_priority(existing_indices: frozenset[int]) -> None:
    """Property 6: first_existing_audio_path returns highest-priority existing path.

    Varies which subset of the three candidate paths exist on disk and asserts
    the returned path is always the lowest-index (highest-priority) existing candidate.
    If no candidates exist, asserts the result is None.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        music_dir = Path(tmp_dir)
        ds = DownloadService(music_dir, concurrency=1)

        title = "My Song"
        artist = "My Artist"
        album = "My Album"
        source_id = "dQw4w9WgXcQ"

        # Build the three candidates in priority order (matching first_existing_audio_path)
        candidates = [
            ds.unique_audio_path(title, artist, album, source_id),
            music_dir / _safe_name(artist) / f"{_safe_name(title)}.mp3",
            music_dir / _safe_name(artist) / _safe_name(album) / f"{_safe_name(title)}.mp3",
        ]

        # Create only the files whose indices are in existing_indices
        for idx in existing_indices:
            path = candidates[idx]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"audio data")

        result = ds.first_existing_audio_path(title, artist, album, source_id)

        if not existing_indices:
            assert result is None
        else:
            # The result must be the candidate with the lowest index (highest priority)
            expected_idx = min(existing_indices)
            assert result == candidates[expected_idx]
