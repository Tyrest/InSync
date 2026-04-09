"""Tests for Jellyfin client helpers (ordered resolution)."""

import asyncio
from unittest.mock import AsyncMock, patch

from app.services.jellyfin import JellyfinClient


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_resolve_preserves_order() -> None:
    jf = JellyfinClient("http://jf.local", api_key="key")
    fake_map = {
        "/music/a/song1.mp3": "id-1",
        "/music/b/song2.mp3": "id-2",
        "/music/c/song3.mp3": "id-3",
    }
    with patch.object(jf, "_build_path_id_map", new_callable=AsyncMock, return_value=fake_map):
        result = _run(
            jf.resolve_item_ids_by_paths(
                "user1",
                [
                    "/music/c/song3.mp3",
                    "/music/a/song1.mp3",
                    "/music/b/song2.mp3",
                ],
            )
        )
    assert result == ["id-3", "id-1", "id-2"]


def test_resolve_skips_unknown_paths() -> None:
    jf = JellyfinClient("http://jf.local", api_key="key")
    fake_map = {"/music/a/song1.mp3": "id-1"}
    with patch.object(jf, "_build_path_id_map", new_callable=AsyncMock, return_value=fake_map):
        result = _run(
            jf.resolve_item_ids_by_paths(
                "user1",
                [
                    "/music/a/song1.mp3",
                    "/music/nonexistent.mp3",
                ],
            )
        )
    assert result == ["id-1"]


def test_resolve_empty_returns_empty() -> None:
    jf = JellyfinClient("http://jf.local", api_key="key")
    result = _run(jf.resolve_item_ids_by_paths("user1", []))
    assert result == []
