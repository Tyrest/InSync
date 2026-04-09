from pathlib import Path


def tag_audio_file(file_path: Path, title: str, artist: str, album: str) -> None:
    """
    Placeholder for mutagen tagging.

    Kept side-effect free for now; mutagen integration can write tags in a future pass.
    """
    _ = (file_path, title, artist, album)
