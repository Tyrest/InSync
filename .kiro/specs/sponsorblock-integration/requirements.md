# Requirements Document

## Introduction

This feature integrates the SponsorBlock community database into InSync's audio download pipeline. After a track is downloaded via yt-dlp, the system queries the SponsorBlock API for timestamped segments (sponsors, intros, outros, self-promotion, interaction reminders, and filler content) associated with the YouTube video ID. Matched segments are then removed from the audio file using FFmpeg, producing a clean track before it is tagged and stored in the Jellyfin library.

SponsorBlock integration is opt-in and configurable per segment category. When disabled, the download pipeline is unchanged.

## Glossary

- **SponsorBlock_Client**: The InSync component responsible for querying the SponsorBlock public API (`https://sponsor.ajay.app/api/`) and returning segment data.
- **Segment**: A timestamped region of a YouTube video identified by the SponsorBlock community as belonging to a specific category (e.g., sponsor, intro, outro).
- **Segment_Category**: One of the SponsorBlock-defined content types: `sponsor`, `intro`, `outro`, `selfpromo`, `interaction`, `music_offtopic`, `filler`.
- **Audio_Trimmer**: The InSync component that removes segments from a downloaded audio file using FFmpeg, producing a trimmed output file.
- **Download_Pipeline**: The sequence of steps executed by `DownloadService` for each track: yt-dlp download → SponsorBlock lookup → audio trimming → metadata tagging → file storage.
- **YouTube_Video_ID**: An 11-character alphanumeric identifier for a YouTube video, used as the key for SponsorBlock API lookups.
- **Settings**: The pydantic-settings `Settings` class in `app/config.py`, loaded from environment variables or `.env`.
- **AppConfig**: The database-backed key/value store (`app_config` table) used for runtime configuration.

---

## Requirements

### Requirement 1: SponsorBlock Feature Toggle

**User Story:** As a self-hoster, I want to enable or disable SponsorBlock integration globally, so that I can opt in to segment removal without affecting existing deployments by default.

#### Acceptance Criteria

1. THE Settings SHALL include a `sponsorblock_enabled` boolean field that defaults to `False`.
2. WHEN `sponsorblock_enabled` is `False`, THE Download_Pipeline SHALL skip all SponsorBlock API calls and audio trimming steps.
3. WHEN `sponsorblock_enabled` is `True`, THE Download_Pipeline SHALL perform SponsorBlock lookup and audio trimming for every newly downloaded track that has a valid YouTube_Video_ID.
4. THE Settings SHALL allow `sponsorblock_enabled` to be configured via the `SPONSORBLOCK_ENABLED` environment variable.

---

### Requirement 2: Configurable Segment Categories

**User Story:** As a self-hoster, I want to choose which SponsorBlock segment categories are removed, so that I can keep content I find acceptable (e.g., intros) while removing content I find unwanted (e.g., sponsors).

#### Acceptance Criteria

1. THE Settings SHALL include a `sponsorblock_categories` field containing a comma-separated list of Segment_Category values, configurable via the `SPONSORBLOCK_CATEGORIES` environment variable.
2. THE Settings SHALL default `sponsorblock_categories` to `"sponsor,intro,outro,selfpromo"`.
3. WHEN the SponsorBlock_Client queries the API, THE SponsorBlock_Client SHALL request only the Segment_Category values present in `sponsorblock_categories`.
4. IF `sponsorblock_categories` is set to an empty string, THEN THE Download_Pipeline SHALL skip SponsorBlock lookup and audio trimming as if `sponsorblock_enabled` were `False`.
5. THE Settings SHALL validate that each value in `sponsorblock_categories` is one of the recognised Segment_Category values: `sponsor`, `intro`, `outro`, `selfpromo`, `interaction`, `music_offtopic`, `filler`.

---

### Requirement 3: SponsorBlock API Lookup

**User Story:** As a self-hoster, I want InSync to fetch segment data from the SponsorBlock public API, so that accurate community-sourced timestamps are used for trimming.

#### Acceptance Criteria

1. WHEN a track download completes and `sponsorblock_enabled` is `True`, THE SponsorBlock_Client SHALL query `https://sponsor.ajay.app/api/skipSegments` with the YouTube_Video_ID and the configured Segment_Category values.
2. WHEN the SponsorBlock API returns HTTP 200, THE SponsorBlock_Client SHALL parse the response into a list of segments, each containing a `start` time in seconds and an `end` time in seconds.
3. WHEN the SponsorBlock API returns HTTP 404, THE SponsorBlock_Client SHALL return an empty segment list, indicating no community data exists for that video.
4. IF the SponsorBlock API returns an HTTP error other than 404, THEN THE SponsorBlock_Client SHALL log a warning and return an empty segment list so that the track is stored without trimming.
5. IF the SponsorBlock API request exceeds 10 seconds, THEN THE SponsorBlock_Client SHALL cancel the request, log a warning, and return an empty segment list.
6. THE SponsorBlock_Client SHALL only perform lookups for tracks whose `source_id` matches the YouTube_Video_ID format (11-character alphanumeric string).

---

### Requirement 4: Audio Segment Removal

**User Story:** As a self-hoster, I want identified segments to be cut out of the downloaded audio file, so that the stored track plays without sponsor reads, intros, or outros.

#### Acceptance Criteria

1. WHEN the SponsorBlock_Client returns one or more segments, THE Audio_Trimmer SHALL remove those segments from the downloaded audio file using FFmpeg.
2. WHEN the SponsorBlock_Client returns an empty segment list, THE Audio_Trimmer SHALL leave the downloaded audio file unchanged.
3. THE Audio_Trimmer SHALL preserve the original audio codec and quality during trimming (no re-encoding).
4. THE Audio_Trimmer SHALL overwrite the original downloaded file with the trimmed output upon successful completion.
5. IF FFmpeg exits with a non-zero status during trimming, THEN THE Audio_Trimmer SHALL log an error, discard the partial output, and retain the original untrimmed file so that the track is still stored.
6. THE Audio_Trimmer SHALL handle overlapping segments by merging them into a single contiguous removal region before invoking FFmpeg.
7. WHEN segments cover the entire audio file duration, THE Audio_Trimmer SHALL log a warning and retain the original untrimmed file rather than producing an empty output.

---

### Requirement 5: Pipeline Integration

**User Story:** As a self-hoster, I want SponsorBlock processing to happen automatically after each download, so that no manual steps are required to get clean tracks.

#### Acceptance Criteria

1. WHEN a track is successfully downloaded by yt-dlp, THE Download_Pipeline SHALL invoke SponsorBlock lookup and audio trimming before invoking metadata tagging.
2. IF SponsorBlock lookup or audio trimming fails for a track, THEN THE Download_Pipeline SHALL log the failure, continue with metadata tagging on the untrimmed file, and mark the download task as `completed` rather than `failed`.
3. THE Download_Pipeline SHALL not invoke SponsorBlock processing for tracks that were already present on disk and skipped re-download.
4. THE Download_Pipeline SHALL not invoke SponsorBlock processing for tracks whose `source_id` does not match the YouTube_Video_ID format.

---

### Requirement 6: Observability

**User Story:** As a self-hoster, I want to see whether SponsorBlock processing occurred for a track, so that I can diagnose issues and verify the feature is working.

#### Acceptance Criteria

1. WHEN SponsorBlock segments are found and trimming is applied, THE Download_Pipeline SHALL log the YouTube_Video_ID, the number of segments removed, and the total duration removed in seconds at `INFO` level.
2. WHEN the SponsorBlock API returns no segments for a video, THE Download_Pipeline SHALL log the YouTube_Video_ID and a message indicating no segments were found at `DEBUG` level.
3. WHEN SponsorBlock lookup is skipped because `sponsorblock_enabled` is `False` or `sponsorblock_categories` is empty, THE Download_Pipeline SHALL not emit any SponsorBlock-related log entries.
4. IF SponsorBlock lookup or trimming raises an exception, THEN THE Download_Pipeline SHALL log the YouTube_Video_ID and the exception message at `WARNING` level.
