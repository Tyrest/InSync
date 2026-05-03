"""Property-based tests for SponsorBlock integration using Hypothesis.

Feature: sponsorblock-integration
"""

import asyncio
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.config import VALID_SPONSORBLOCK_CATEGORIES, Settings
from app.services.audio_trimmer import AudioTrimmer, TrimSegment
from app.services.sponsorblock import SponsorBlockClient
from hypothesis import HealthCheck, given
from hypothesis import settings as h_settings
from hypothesis import strategies as st

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


def _patch_httpx_client(mock_response):
    """Return a context-manager patch for httpx.AsyncClient that yields mock_response on .get()."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return patch("httpx.AsyncClient", return_value=mock_ctx), mock_client


def _make_mock_response(status_code: int, json_data=None):
    """Build a mock httpx response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    if json_data is not None:
        mock_resp.json.return_value = json_data
    return mock_resp


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid YouTube ID: 11 chars from [a-zA-Z0-9_-]
valid_yt_id = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"),
    min_size=11,
    max_size=11,
)

# Valid categories subset
valid_categories_subset = st.frozensets(
    st.sampled_from(sorted(VALID_SPONSORBLOCK_CATEGORIES)),
    min_size=1,
)

# TrimSegment pairs
trim_segment_strategy = st.builds(
    TrimSegment,
    start=st.floats(min_value=0, max_value=99, allow_nan=False, allow_infinity=False),
    end=st.floats(min_value=1, max_value=100, allow_nan=False, allow_infinity=False),
).filter(lambda s: s.start < s.end)


# ---------------------------------------------------------------------------
# Property 1: SponsorBlock lookup is called for every valid YouTube ID
# Feature: sponsorblock-integration, Property 1
# Validates: Requirements 1.3, 5.4
# ---------------------------------------------------------------------------


@given(video_id=valid_yt_id)
@h_settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_sponsorblock_called_for_valid_youtube_ids(video_id: str) -> None:
    """Property 1: _apply_sponsorblock calls get_segments with the video ID for any valid YouTube ID."""
    from app.services.audio_trimmer import AudioTrimmer
    from app.services.download import DownloadService

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        mock_client = AsyncMock()
        mock_client.get_segments = AsyncMock(return_value=[])
        mock_trimmer = MagicMock(spec=AudioTrimmer)

        ds = DownloadService(
            music_dir=tmp_path,
            concurrency=1,
            sponsorblock_client=mock_client,
            audio_trimmer=mock_trimmer,
        )

        audio_file = tmp_path / "track.opus"
        audio_file.write_bytes(b"audio data")

        _run(ds._apply_sponsorblock(audio_file, video_id))

        mock_client.get_segments.assert_called_once_with(video_id)


# ---------------------------------------------------------------------------
# Property 2: API request categories match configured categories exactly
# Feature: sponsorblock-integration, Property 2
# Validates: Requirements 2.3, 3.1
# ---------------------------------------------------------------------------


@given(categories=valid_categories_subset)
@h_settings(max_examples=100)
def test_api_request_categories_match_configured(categories: frozenset) -> None:
    """Property 2: The categories query parameter in the HTTP request matches the configured list."""
    categories_list = list(categories)
    mock_resp = _make_mock_response(200, [])
    patcher, mock_client = _patch_httpx_client(mock_resp)

    client = SponsorBlockClient(categories=categories_list)
    with patcher:
        _run(client.get_segments("dQw4w9WgXcQ"))

    # Verify get was called
    mock_client.get.assert_called_once()
    call_kwargs = mock_client.get.call_args

    # Extract the params from the call
    if call_kwargs.kwargs.get("params"):
        params = call_kwargs.kwargs["params"]
    else:
        params = call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs.get("params", {})

    # The categories param should be JSON-encoded
    categories_param = params["categories"]
    decoded = json.loads(categories_param)
    assert sorted(decoded) == sorted(categories_list)


# ---------------------------------------------------------------------------
# Property 3: Settings validation rejects invalid category names
# Feature: sponsorblock-integration, Property 3
# Validates: Requirements 2.5
# ---------------------------------------------------------------------------

# Generate strings that are NOT valid categories
invalid_category_strategy = st.text(min_size=1).filter(
    lambda s: s.strip() not in VALID_SPONSORBLOCK_CATEGORIES and s.strip() != ""
)


@given(invalid_cat=invalid_category_strategy)
@h_settings(max_examples=100)
def test_settings_rejects_invalid_categories(invalid_cat: str) -> None:
    """Property 3: Settings raises ValueError for any string not in VALID_SPONSORBLOCK_CATEGORIES."""
    s = Settings(sponsorblock_categories=invalid_cat)
    with pytest.raises(ValueError, match="Invalid SponsorBlock categories"):
        _ = s.sponsorblock_category_list


# ---------------------------------------------------------------------------
# Property 4: API response parsing round-trip
# Feature: sponsorblock-integration, Property 4
# Validates: Requirements 3.2
# ---------------------------------------------------------------------------

segment_triple_strategy = st.tuples(
    st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
    st.sampled_from(sorted(VALID_SPONSORBLOCK_CATEGORIES)),
).filter(lambda t: t[0] < t[1])


@given(triples=st.lists(segment_triple_strategy, min_size=0, max_size=20))
@h_settings(max_examples=100)
def test_api_response_parsing_round_trip(triples: list) -> None:
    """Property 4: Parsing SponsorBlock API JSON produces SponsorSegment objects with identical values."""
    from app.services.sponsorblock import SponsorSegment

    # Serialize to SponsorBlock API JSON format
    api_body = [{"segment": [start, end], "category": cat} for start, end, cat in triples]
    mock_resp = _make_mock_response(200, api_body)
    patcher, _ = _patch_httpx_client(mock_resp)

    client = SponsorBlockClient(categories=list(VALID_SPONSORBLOCK_CATEGORIES))
    with patcher:
        result = _run(client.get_segments("dQw4w9WgXcQ"))

    assert len(result) == len(triples)
    for seg, (start, end, cat) in zip(result, triples):
        assert isinstance(seg, SponsorSegment)
        assert seg.start == float(start)
        assert seg.end == float(end)
        assert seg.category == cat


# ---------------------------------------------------------------------------
# Property 5: Non-404 HTTP errors always return empty segment list
# Feature: sponsorblock-integration, Property 5
# Validates: Requirements 3.4
# ---------------------------------------------------------------------------

error_status_codes = st.sampled_from([400, 401, 403, 429, 500, 502, 503])


@given(status_code=error_status_codes)
@h_settings(max_examples=100)
def test_non_404_errors_return_empty_list(status_code: int) -> None:
    """Property 5: Any non-404 HTTP error returns an empty list without raising."""
    mock_resp = _make_mock_response(status_code)
    patcher, _ = _patch_httpx_client(mock_resp)

    client = SponsorBlockClient(categories=["sponsor"])
    with patcher:
        result = _run(client.get_segments("dQw4w9WgXcQ"))

    assert result == []


# ---------------------------------------------------------------------------
# Property 6: Invalid YouTube IDs never trigger an HTTP request
# Feature: sponsorblock-integration, Property 6
# Validates: Requirements 3.6, 5.4
# ---------------------------------------------------------------------------

# Generate strings that don't match ^[a-zA-Z0-9_-]{11}$
invalid_yt_id_strategy = st.one_of(
    # Wrong length (not 11)
    st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"),
        min_size=0,
        max_size=10,
    ),
    st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"),
        min_size=12,
        max_size=30,
    ),
    # 11 chars but with invalid characters
    st.text(min_size=11, max_size=11).filter(
        lambda s: not all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in s)
    ),
)


@given(invalid_id=invalid_yt_id_strategy)
@h_settings(max_examples=100)
def test_invalid_youtube_ids_no_http_request(invalid_id: str) -> None:
    """Property 6: Invalid YouTube IDs return empty list without making any HTTP request."""
    client = SponsorBlockClient(categories=["sponsor"])
    with patch("httpx.AsyncClient") as mock_cls:
        result = _run(client.get_segments(invalid_id))

    assert result == []
    mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Property 7: Segment merging produces non-overlapping intervals with identical coverage
# Feature: sponsorblock-integration, Property 7
# Validates: Requirements 4.6
# ---------------------------------------------------------------------------

interval_strategy = st.tuples(
    st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
).filter(lambda t: t[0] < t[1])


def _compute_coverage(intervals: list) -> float:
    """Compute total covered time from a list of (start, end) or TrimSegment objects."""
    if not intervals:
        return 0.0
    # Normalize to (start, end) tuples
    pairs = []
    for item in intervals:
        if isinstance(item, TrimSegment):
            pairs.append((item.start, item.end))
        else:
            pairs.append((item[0], item[1]))
    # Merge and sum
    sorted_pairs = sorted(pairs, key=lambda x: x[0])
    merged = [sorted_pairs[0]]
    for start, end in sorted_pairs[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return sum(end - start for start, end in merged)


@given(intervals=st.lists(interval_strategy, min_size=0, max_size=30))
@h_settings(max_examples=100)
def test_merge_overlapping_produces_valid_intervals(intervals: list) -> None:
    """Property 7: merge_overlapping returns sorted, non-overlapping intervals with same coverage."""
    segments = [TrimSegment(start=s, end=e) for s, e in intervals]
    result = AudioTrimmer.merge_overlapping(segments)

    # Result must be sorted by start time
    for i in range(len(result) - 1):
        assert result[i].start <= result[i + 1].start, "Result is not sorted by start time"

    # No two intervals in result should overlap
    for i in range(len(result) - 1):
        assert result[i].end <= result[i + 1].start, (
            f"Intervals overlap: [{result[i].start}, {result[i].end}] and [{result[i + 1].start}, {result[i + 1].end}]"
        )

    # Coverage must be identical
    input_coverage = _compute_coverage(intervals)
    result_coverage = _compute_coverage(result)
    assert abs(input_coverage - result_coverage) < 1e-9, (
        f"Coverage mismatch: input={input_coverage}, result={result_coverage}"
    )


# ---------------------------------------------------------------------------
# Property 8: Trimming always uses stream copy (no re-encoding)
# Feature: sponsorblock-integration, Property 8
# Validates: Requirements 4.3
# ---------------------------------------------------------------------------


@given(segments=st.lists(trim_segment_strategy, min_size=1, max_size=10))
@h_settings(max_examples=100)
def test_trim_ffmpeg_command_uses_stream_copy(segments: list) -> None:
    """Property 8: The FFmpeg command always includes -c copy for stream copy (no re-encoding)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        audio_file = tmp_path / "track.opus"
        audio_file.write_bytes(b"audio data")

        captured_cmd = []

        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            tmp = Path(cmd[-1])
            tmp.write_bytes(b"trimmed")
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        trimmer = AudioTrimmer()
        with patch("subprocess.run", side_effect=fake_run):
            trimmer.trim(audio_file, segments, 200.0)

        # Assert the command contains -c copy
        assert "-c" in captured_cmd, f"Expected '-c' in command args: {captured_cmd}"
        c_index = captured_cmd.index("-c")
        assert captured_cmd[c_index + 1] == "copy", f"Expected 'copy' after '-c', got: {captured_cmd[c_index + 1]}"


# ---------------------------------------------------------------------------
# Property 9: Pipeline resilience — SponsorBlock failures never fail the download
# Feature: sponsorblock-integration, Property 9
# Validates: Requirements 5.2, 6.4
# ---------------------------------------------------------------------------

exception_types_strategy = st.sampled_from([ValueError, RuntimeError, OSError, KeyError, TypeError])


@given(exc_type=exception_types_strategy, message=st.text(max_size=100))
@h_settings(max_examples=100)
def test_pipeline_resilience_sponsorblock_failure(exc_type: type, message: str) -> None:
    """Property 9: Any exception from get_segments is caught; _apply_sponsorblock never raises."""
    from app.services.audio_trimmer import AudioTrimmer
    from app.services.download import DownloadService

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        mock_client = AsyncMock()
        mock_client.get_segments = AsyncMock(side_effect=exc_type(message))
        mock_trimmer = MagicMock(spec=AudioTrimmer)

        ds = DownloadService(
            music_dir=tmp_path,
            concurrency=1,
            sponsorblock_client=mock_client,
            audio_trimmer=mock_trimmer,
        )

        audio_file = tmp_path / "track.opus"
        audio_file.write_bytes(b"audio data")

        # Must not raise
        _run(ds._apply_sponsorblock(audio_file, "dQw4w9WgXcQ"))


# ---------------------------------------------------------------------------
# Property 10: Trimming info log contains video ID, segment count, and total duration
# Feature: sponsorblock-integration, Property 10
# Validates: Requirements 6.1
# ---------------------------------------------------------------------------

sponsor_segment_strategy = st.tuples(
    st.floats(min_value=0.0, max_value=299.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=1.0, max_value=300.0, allow_nan=False, allow_infinity=False),
    st.sampled_from(sorted(VALID_SPONSORBLOCK_CATEGORIES)),
).filter(lambda t: t[0] < t[1])


@given(
    video_id=valid_yt_id,
    segment_triples=st.lists(sponsor_segment_strategy, min_size=1, max_size=10),
)
@h_settings(max_examples=100)
def test_trim_info_log_contains_required_fields(
    video_id: str,
    segment_triples: list,
) -> None:
    """Property 10: INFO log entry contains video ID, segment count, and total duration removed."""
    from app.services.audio_trimmer import AudioTrimmer
    from app.services.download import DownloadService
    from app.services.sponsorblock import SponsorSegment

    segments = [SponsorSegment(start=s, end=e, category=c) for s, e, c in segment_triples]

    mock_client = AsyncMock()
    mock_client.get_segments = AsyncMock(return_value=segments)

    mock_trimmer = MagicMock(spec=AudioTrimmer)
    mock_trimmer.trim = MagicMock(return_value=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        ds = DownloadService(
            music_dir=tmp_path,
            concurrency=1,
            sponsorblock_client=mock_client,
            audio_trimmer=mock_trimmer,
        )

        audio_file = tmp_path / "track.opus"
        audio_file.write_bytes(b"audio data")

        mock_mutagen_info = MagicMock()
        mock_mutagen_info.info.length = 300.0
        mock_mutagen_file = MagicMock(return_value=mock_mutagen_info)

        # Use a manual log handler to capture records (avoids function-scoped caplog fixture)
        log_records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                log_records.append(record)

        handler = _Capture()
        handler.setLevel(logging.INFO)
        logger = logging.getLogger("app.services.download")
        old_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        try:
            with patch("mutagen.File", mock_mutagen_file):
                _run(ds._apply_sponsorblock(audio_file, video_id))
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)

    # Find INFO log records from the download service
    info_records = [r for r in log_records if r.levelno == logging.INFO and "SponsorBlock" in r.getMessage()]
    assert len(info_records) >= 1, f"Expected at least one INFO SponsorBlock log entry, got: {log_records}"

    log_message = info_records[0].getMessage()

    # Assert video ID is in the log
    assert video_id in log_message, f"Expected video_id={video_id!r} in log: {log_message!r}"

    # Assert segment count is in the log
    segment_count = len(segments)
    assert str(segment_count) in log_message, f"Expected segment count={segment_count} in log: {log_message!r}"

    # Assert total duration is mentioned
    total_removed = sum(seg.end - seg.start for seg in segments)
    assert "duration" in log_message.lower() or f"{total_removed:.3f}" in log_message, (
        f"Expected total duration={total_removed:.3f} in log: {log_message!r}"
    )
