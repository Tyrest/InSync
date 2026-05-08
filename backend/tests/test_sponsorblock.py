"""Unit tests for SponsorBlockClient, AudioTrimmer, and Settings (SponsorBlock fields)."""

import asyncio
import logging
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.audio_trimmer import AudioTrimmer, TrimSegment
from app.services.sponsorblock import SponsorBlockClient, SponsorSegment

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine synchronously in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_mock_response(status_code: int, json_data=None):
    """Build a mock httpx response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    if json_data is not None:
        mock_resp.json.return_value = json_data
    return mock_resp


def _patch_httpx_client(mock_response):
    """Return a context-manager patch for httpx.AsyncClient that yields mock_response on .get()."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return patch("httpx.AsyncClient", return_value=mock_ctx), mock_client


# ---------------------------------------------------------------------------
# 6.1  HTTP 200 → correct SponsorSegment list
# ---------------------------------------------------------------------------


def test_get_segments_http_200_returns_segment_list():
    response_body = [
        {"segment": [10.5, 30.0], "category": "sponsor"},
        {"segment": [60.0, 90.5], "category": "intro"},
    ]
    mock_resp = _make_mock_response(200, response_body)
    patcher, _ = _patch_httpx_client(mock_resp)

    client = SponsorBlockClient(categories=["sponsor", "intro"])
    with patcher:
        result = _run(client.get_segments("dQw4w9WgXcQ"))

    assert result == [
        SponsorSegment(start=10.5, end=30.0, category="sponsor"),
        SponsorSegment(start=60.0, end=90.5, category="intro"),
    ]


# ---------------------------------------------------------------------------
# 6.2  HTTP 404 → empty list
# ---------------------------------------------------------------------------


def test_get_segments_http_404_returns_empty():
    mock_resp = _make_mock_response(404)
    patcher, _ = _patch_httpx_client(mock_resp)

    client = SponsorBlockClient(categories=["sponsor"])
    with patcher:
        result = _run(client.get_segments("dQw4w9WgXcQ"))

    assert result == []


# ---------------------------------------------------------------------------
# 6.3  HTTP 500 → empty list, warning logged
# ---------------------------------------------------------------------------


def test_get_segments_http_500_returns_empty_and_logs_warning(caplog):
    mock_resp = _make_mock_response(500)
    patcher, _ = _patch_httpx_client(mock_resp)

    client = SponsorBlockClient(categories=["sponsor"])
    with caplog.at_level(logging.WARNING, logger="app.services.sponsorblock"), patcher:
        result = _run(client.get_segments("dQw4w9WgXcQ"))

    assert result == []
    assert any("500" in record.message or "unexpected" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# 6.4  Timeout → empty list, warning logged
# ---------------------------------------------------------------------------


def test_get_segments_timeout_returns_empty_and_logs_warning(caplog):
    import httpx

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    client = SponsorBlockClient(categories=["sponsor"])
    with (
        caplog.at_level(logging.WARNING, logger="app.services.sponsorblock"),
        patch("httpx.AsyncClient", return_value=mock_ctx),
    ):
        result = _run(client.get_segments("dQw4w9WgXcQ"))

    assert result == []
    assert any(
        "timed out" in record.message.lower() or "timeout" in record.message.lower() for record in caplog.records
    )


# ---------------------------------------------------------------------------
# 6.5  Invalid video ID (wrong length) → empty list, no HTTP call
# ---------------------------------------------------------------------------


def test_get_segments_invalid_id_wrong_length_no_http_call():
    client = SponsorBlockClient(categories=["sponsor"])
    with patch("httpx.AsyncClient") as mock_cls:
        result = _run(client.get_segments("short"))  # only 5 chars

    assert result == []
    mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# 6.6  Invalid video ID (invalid chars) → empty list, no HTTP call
# ---------------------------------------------------------------------------


def test_get_segments_invalid_id_bad_chars_no_http_call():
    client = SponsorBlockClient(categories=["sponsor"])
    with patch("httpx.AsyncClient") as mock_cls:
        result = _run(client.get_segments("dQw4w9WgX!@"))  # 11 chars but contains !@

    assert result == []
    mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# 6.7  AudioTrimmer.merge_overlapping
# ---------------------------------------------------------------------------


def test_merge_overlapping_empty():
    assert AudioTrimmer.merge_overlapping([]) == []


def test_merge_overlapping_single():
    result = AudioTrimmer.merge_overlapping([TrimSegment(10, 20)])
    assert result == [TrimSegment(10, 20)]


def test_merge_overlapping_non_overlapping():
    segs = [TrimSegment(20, 30), TrimSegment(0, 10)]  # unsorted on purpose
    result = AudioTrimmer.merge_overlapping(segs)
    assert result == [TrimSegment(0, 10), TrimSegment(20, 30)]


def test_merge_overlapping_overlapping():
    segs = [TrimSegment(0, 20), TrimSegment(10, 30)]
    result = AudioTrimmer.merge_overlapping(segs)
    assert result == [TrimSegment(0, 30)]


def test_merge_overlapping_nested():
    segs = [TrimSegment(0, 30), TrimSegment(10, 20)]
    result = AudioTrimmer.merge_overlapping(segs)
    assert result == [TrimSegment(0, 30)]


def test_merge_overlapping_adjacent():
    segs = [TrimSegment(0, 10), TrimSegment(10, 20)]
    result = AudioTrimmer.merge_overlapping(segs)
    assert result == [TrimSegment(0, 20)]


# ---------------------------------------------------------------------------
# 6.8  AudioTrimmer.trim
# ---------------------------------------------------------------------------


def test_trim_empty_segments_is_noop(tmp_path: Path):
    audio = tmp_path / "track.opus"
    audio.write_bytes(b"audio data")

    trimmer = AudioTrimmer()
    with patch("subprocess.run") as mock_run:
        result = trimmer.trim(audio, [], 100.0)

    assert result is True
    mock_run.assert_not_called()
    assert audio.read_bytes() == b"audio data"  # unchanged


def test_trim_full_coverage_is_noop_with_warning(tmp_path: Path, caplog):
    audio = tmp_path / "track.opus"
    audio.write_bytes(b"audio data")

    trimmer = AudioTrimmer()
    with caplog.at_level(logging.WARNING, logger="app.services.audio_trimmer"), patch("subprocess.run") as mock_run:
        result = trimmer.trim(audio, [TrimSegment(0, 100)], 100.0)

    assert result is True
    mock_run.assert_not_called()
    assert any(
        "entire file" in record.message.lower() or "skipping" in record.message.lower() for record in caplog.records
    )


def test_trim_ffmpeg_success_overwrites_original(tmp_path: Path):
    audio = tmp_path / "track.opus"
    audio.write_bytes(b"original audio")

    trimmer = AudioTrimmer()

    def fake_run(cmd, **kwargs):
        # Simulate FFmpeg writing the tmp output file
        tmp = Path(cmd[-1])  # last arg is the output path
        tmp.write_bytes(b"trimmed audio")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with patch("subprocess.run", side_effect=fake_run):
        result = trimmer.trim(audio, [TrimSegment(10, 30)], 100.0)

    assert result is True
    assert audio.read_bytes() == b"trimmed audio"


def test_trim_ffmpeg_nonzero_exit_retains_original(tmp_path: Path):
    audio = tmp_path / "track.opus"
    audio.write_bytes(b"original audio")

    trimmer = AudioTrimmer()

    def fake_run(cmd, **kwargs):
        # Simulate FFmpeg writing a partial tmp file then failing
        tmp = Path(cmd[-1])
        tmp.write_bytes(b"partial")
        return subprocess.CompletedProcess(args=cmd, returncode=1, stderr=b"error: something went wrong")

    with patch("subprocess.run", side_effect=fake_run):
        result = trimmer.trim(audio, [TrimSegment(10, 30)], 100.0)

    assert result is False
    assert audio.read_bytes() == b"original audio"
    # Temp file should be cleaned up
    tmp_path_file = audio.with_suffix(audio.suffix + ".tmp")
    assert not tmp_path_file.exists()


# ---------------------------------------------------------------------------
# 6.9  Settings defaults
# ---------------------------------------------------------------------------


def test_settings_defaults():
    from app.config import Settings

    s = Settings()
    assert s.sponsorblock_enabled is False
    assert s.sponsorblock_categories == "sponsor,intro,outro,selfpromo"


# ---------------------------------------------------------------------------
# 6.10  Settings with valid SPONSORBLOCK_CATEGORIES env var
# ---------------------------------------------------------------------------


def test_settings_valid_categories_env_var(monkeypatch):
    monkeypatch.setenv("SPONSORBLOCK_CATEGORIES", "sponsor,outro,filler")

    from app.config import Settings

    s = Settings()
    assert s.sponsorblock_category_list == ["sponsor", "outro", "filler"]


# ---------------------------------------------------------------------------
# 6.11  Settings with invalid category name → ValidationError
# ---------------------------------------------------------------------------


def test_settings_invalid_category_raises_validation_error(monkeypatch):
    monkeypatch.setenv("SPONSORBLOCK_CATEGORIES", "sponsor,not_a_real_category")

    from app.config import Settings

    s = Settings()
    with pytest.raises(ValueError, match="Invalid SponsorBlock categories"):
        _ = s.sponsorblock_category_list


# ---------------------------------------------------------------------------
# 6.12  Settings with empty SPONSORBLOCK_CATEGORIES → empty list
# ---------------------------------------------------------------------------


def test_settings_empty_categories_returns_empty_list(monkeypatch):
    monkeypatch.setenv("SPONSORBLOCK_CATEGORIES", "")

    from app.config import Settings

    s = Settings()
    assert s.sponsorblock_category_list == []
