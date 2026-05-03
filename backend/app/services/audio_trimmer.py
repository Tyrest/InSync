import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrimSegment:
    start: float
    end: float


class AudioTrimmer:
    def __init__(self, ffmpeg_path: str = "ffmpeg") -> None:
        self._ffmpeg_path = ffmpeg_path

    @staticmethod
    def merge_overlapping(segments: list[TrimSegment]) -> list[TrimSegment]:
        """Merge overlapping or adjacent segments into a minimal non-overlapping list.

        Returns segments sorted by start time with all overlaps resolved.
        """
        if not segments:
            return []

        sorted_segs = sorted(segments, key=lambda s: s.start)
        merged: list[TrimSegment] = [sorted_segs[0]]

        for seg in sorted_segs[1:]:
            last = merged[-1]
            if seg.start <= last.end:
                # Overlapping or adjacent — extend the current interval if needed
                if seg.end > last.end:
                    merged[-1] = TrimSegment(start=last.start, end=seg.end)
            else:
                merged.append(seg)

        return merged

    def trim(self, audio_path: Path, segments: list[TrimSegment], duration: float) -> bool:
        """Remove the given segments from audio_path in-place.

        - Merges overlapping segments before processing.
        - If segments is empty, returns True immediately (no-op).
        - If merged segments cover the entire file, logs a warning and returns True (no-op).
        - Uses FFmpeg with -c copy (no re-encoding).
        - On FFmpeg failure, logs error, discards partial output, returns False.
        - On success, overwrites audio_path with the trimmed output.

        Returns True if the file was processed successfully (or was a no-op),
        False if FFmpeg failed.
        """
        if not segments:
            return True

        merged = self.merge_overlapping(segments)

        # Check if merged segments cover the entire file
        if merged[0].start <= 0 and merged[-1].end >= duration:
            log.warning(
                "AudioTrimmer: segments cover entire file %s (duration=%.3f), skipping trim",
                audio_path,
                duration,
            )
            return True

        # Compute keep-regions as the inverse of the merged remove-segments
        keep_regions: list[tuple[float, float]] = []
        cursor = 0.0
        for seg in merged:
            if seg.start > cursor:
                keep_regions.append((cursor, seg.start))
            cursor = seg.end
        if cursor < duration:
            keep_regions.append((cursor, duration))

        # Build filter_complex using atrim + asetpts for each keep region, then aconcat
        filter_parts: list[str] = []
        for i, (start, end) in enumerate(keep_regions):
            filter_parts.append(f"[0:a]atrim=start={start}:end={end},asetpts=N/SR/TB[seg{i}]")

        n = len(keep_regions)
        concat_inputs = "".join(f"[seg{i}]" for i in range(n))
        filter_parts.append(f"{concat_inputs}aconcat=n={n}:v=0:a=1[out]")

        filter_complex = ";".join(filter_parts)

        tmp_path = audio_path.with_suffix(audio_path.suffix + ".tmp")

        cmd = [
            self._ffmpeg_path,
            "-y",
            "-i",
            str(audio_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-c",
            "copy",
            str(tmp_path),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True)  # noqa: S603
        except FileNotFoundError:
            log.error("AudioTrimmer: ffmpeg not found at %r", self._ffmpeg_path)
            return False

        if result.returncode != 0:
            log.error(
                "AudioTrimmer: ffmpeg exited with code %d for %s\nstderr: %s",
                result.returncode,
                audio_path,
                result.stderr.decode(errors="replace"),
            )
            if tmp_path.exists():
                tmp_path.unlink()
            return False

        tmp_path.replace(audio_path)
        return True
