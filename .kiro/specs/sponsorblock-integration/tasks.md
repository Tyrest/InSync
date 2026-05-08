# Tasks

## Task List

- [x] 1. Add SponsorBlock settings to `app/config.py`
  - [x] 1.1 Add `sponsorblock_enabled: bool = False` field to `Settings`
  - [x] 1.2 Add `sponsorblock_categories: str = "sponsor,intro,outro,selfpromo"` field to `Settings`
  - [x] 1.3 Add `VALID_SPONSORBLOCK_CATEGORIES` frozenset constant
  - [x] 1.4 Add `sponsorblock_category_list` computed field that parses the comma-separated string, strips whitespace, validates each entry against `VALID_SPONSORBLOCK_CATEGORIES`, and raises `ValidationError` for unknown values
  - [x] 1.5 Return empty list from `sponsorblock_category_list` when `sponsorblock_categories` is blank

- [x] 2. Implement `SponsorBlockClient` (`backend/app/services/sponsorblock.py`)
  - [x] 2.1 Define `SponsorSegment` frozen dataclass with `start: float`, `end: float`, `category: str`
  - [x] 2.2 Implement `SponsorBlockClient.__init__` accepting `categories: list[str]`
  - [x] 2.3 Implement `get_segments(video_id: str) -> list[SponsorSegment]` — validate video ID format using `_YOUTUBE_VIDEO_ID_RE` before making any HTTP request; return `[]` immediately for invalid IDs
  - [x] 2.4 Build the `httpx` GET request to `https://sponsor.ajay.app/api/skipSegments` with `videoID` and `categories` query parameters (categories JSON-encoded as required by the API)
  - [x] 2.5 Parse HTTP 200 response: extract `segment[0]` (start), `segment[1]` (end), and `category` from each element
  - [x] 2.6 Return `[]` on HTTP 404 (log at DEBUG)
  - [x] 2.7 Return `[]` on any other HTTP error (log WARNING with status code)
  - [x] 2.8 Return `[]` on `httpx.TimeoutException` (log WARNING)
  - [x] 2.9 Return `[]` on any other exception including malformed JSON (log WARNING)

- [x] 3. Implement `AudioTrimmer` (`backend/app/services/audio_trimmer.py`)
  - [x] 3.1 Define `TrimSegment` frozen dataclass with `start: float`, `end: float`
  - [x] 3.2 Implement `AudioTrimmer.__init__` accepting `ffmpeg_path: str = "ffmpeg"`
  - [x] 3.3 Implement `merge_overlapping(segments: list[TrimSegment]) -> list[TrimSegment]` — sort by start, merge overlapping/adjacent intervals, return minimal non-overlapping list
  - [x] 3.4 Implement `trim(audio_path: Path, segments: list[TrimSegment], duration: float) -> bool`:
    - Return `True` immediately (no-op) when `segments` is empty
    - Call `merge_overlapping` on the input segments
    - Log WARNING and return `True` (no-op) when merged segments cover the entire file (`merged[0].start <= 0` and `merged[-1].end >= duration`)
    - Compute keep-regions as the inverse of the merged remove-segments
    - Build FFmpeg `filter_complex` using `aselect` expressions for keep-regions, concatenated with `aconcatenate`
    - Include `-c copy` in the FFmpeg command to prevent re-encoding
    - Write output to a `.tmp` sibling file
    - On FFmpeg success (exit code 0): replace original with temp file via `Path.replace()`; return `True`
    - On FFmpeg non-zero exit: log ERROR, delete temp file, return `False`
    - On `FileNotFoundError` (ffmpeg not on PATH): log ERROR, return `False`

- [x] 4. Integrate SponsorBlock into `DownloadService` (`backend/app/services/download.py`)
  - [x] 4.1 Add optional `sponsorblock_client: SponsorBlockClient | None = None` and `audio_trimmer: AudioTrimmer | None = None` parameters to `DownloadService.__init__`
  - [x] 4.2 Implement `_apply_sponsorblock(self, path: Path, source_id: str) -> None` as an async method:
    - Call `await self._sponsorblock_client.get_segments(source_id)`
    - If no segments returned: log at DEBUG with video ID and "no segments found"; return
    - Get audio duration via `mutagen.File(path).info.length`
    - Call `await asyncio.to_thread(self._audio_trimmer.trim, path, segments, duration)`
    - If trim succeeded: log at INFO with video ID, segment count, and total duration removed
    - Wrap entire method body in `try/except Exception`: log WARNING with video ID and exception message; return (never raise)
  - [x] 4.3 Restructure `_download` to release the semaphore immediately after `_run_download` returns, then call `_apply_sponsorblock` **outside** the `async with self._semaphore` block — this allows all in-flight downloads to run SponsorBlock concurrently without consuming a yt-dlp concurrency slot
  - [x] 4.4 Update `_run_download` to return a `tuple[Path, bool]` (path, is_fresh_download) so the caller can skip `_apply_sponsorblock` for tracks that were already on disk (satisfies Requirement 5.3); the `bool` is `False` when the early-return cached path is taken, `True` after a fresh yt-dlp download

- [x] 5. Wire SponsorBlock services into `AppState` (`backend/app/state.py`)
  - [x] 5.1 Import `SponsorBlockClient` and `AudioTrimmer` in `state.py`
  - [x] 5.2 In `AppState.__init__`, read `settings.sponsorblock_enabled` and `settings.sponsorblock_category_list`
  - [x] 5.3 Conditionally construct `SponsorBlockClient` and `AudioTrimmer` when enabled and categories are non-empty
  - [x] 5.4 Pass both to `DownloadService` constructor

- [x] 6. Write unit tests (`backend/tests/test_sponsorblock.py`)
  - [x] 6.1 Test `SponsorBlockClient.get_segments` with mocked `httpx`: HTTP 200 with known response → correct `SponsorSegment` list
  - [x] 6.2 Test HTTP 404 → empty list
  - [x] 6.3 Test HTTP 500 → empty list, warning logged
  - [x] 6.4 Test timeout → empty list, warning logged
  - [x] 6.5 Test invalid video ID (wrong length) → empty list, no HTTP call
  - [x] 6.6 Test invalid video ID (invalid chars) → empty list, no HTTP call
  - [x] 6.7 Test `AudioTrimmer.merge_overlapping`: empty list, single segment, non-overlapping, overlapping, nested, adjacent
  - [x] 6.8 Test `AudioTrimmer.trim` with mocked `subprocess.run`: empty segments → no-op; full-coverage segments → no-op with warning; FFmpeg success → file overwritten; FFmpeg non-zero exit → original retained
  - [x] 6.9 Test Settings defaults: `sponsorblock_enabled=False`, default categories
  - [x] 6.10 Test Settings with valid `SPONSORBLOCK_CATEGORIES` env var → correct parsed list
  - [x] 6.11 Test Settings with invalid category name → `ValidationError`
  - [x] 6.12 Test Settings with empty `SPONSORBLOCK_CATEGORIES` → empty list, pipeline skips SponsorBlock

- [x] 7. Write property-based tests (`backend/tests/test_sponsorblock_properties.py`)
  - [x] 7.1 Property 1: `test_sponsorblock_called_for_valid_youtube_ids` — generate random valid YouTube video IDs, assert `get_segments` is called for each when enabled
    - Tag: `Feature: sponsorblock-integration, Property 1`
  - [x] 7.2 Property 2: `test_api_request_categories_match_configured` — generate random non-empty subsets of valid categories, mock httpx, assert request categories match configured list exactly
    - Tag: `Feature: sponsorblock-integration, Property 2`
  - [x] 7.3 Property 3: `test_settings_rejects_invalid_categories` — generate random strings not in valid category set, assert `ValidationError` raised
    - Tag: `Feature: sponsorblock-integration, Property 3`
  - [x] 7.4 Property 4: `test_api_response_parsing_round_trip` — generate random `(start, end, category)` triples, mock HTTP 200, assert parsed output matches input
    - Tag: `Feature: sponsorblock-integration, Property 4`
  - [x] 7.5 Property 5: `test_non_404_errors_return_empty_list` — generate random HTTP error codes (not 404), assert empty list returned
    - Tag: `Feature: sponsorblock-integration, Property 5`
  - [x] 7.6 Property 6: `test_invalid_youtube_ids_no_http_request` — generate random strings not matching `^[a-zA-Z0-9_-]{11}$`, assert no HTTP request made and empty list returned
    - Tag: `Feature: sponsorblock-integration, Property 6`
  - [x] 7.7 Property 7: `test_merge_overlapping_produces_valid_intervals` — generate random `(start, end)` pairs, assert result is sorted, non-overlapping, and covers same time ranges as input
    - Tag: `Feature: sponsorblock-integration, Property 7`
  - [x] 7.8 Property 8: `test_trim_ffmpeg_command_uses_stream_copy` — generate random non-empty segment lists, mock subprocess, assert FFmpeg command includes `-c copy`
    - Tag: `Feature: sponsorblock-integration, Property 8`
  - [x] 7.9 Property 9: `test_pipeline_resilience_sponsorblock_failure` — generate random exception types/messages, mock client to raise them, assert task marked `completed` and tagging still called
    - Tag: `Feature: sponsorblock-integration, Property 9`
  - [x] 7.10 Property 10: `test_trim_info_log_contains_required_fields` — generate random non-empty segment lists and valid YouTube IDs, assert INFO log contains video ID, segment count, and total duration
    - Tag: `Feature: sponsorblock-integration, Property 10`

- [x] 8. Run linter and type checker
  - [x] 8.1 Run `uv run ruff check --fix` and `uv run ruff format` from `backend/`
  - [x] 8.2 Run `uv run ty check` from `backend/` and resolve any type errors
  - [x] 8.3 Run `uv run pytest backend/tests/test_sponsorblock.py backend/tests/test_sponsorblock_properties.py` and confirm all tests pass
