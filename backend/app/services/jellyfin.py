import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class JellyfinClient:
    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            headers["X-Emby-Token"] = token
        elif self.api_key:
            headers["X-Emby-Token"] = self.api_key
        return headers

    async def validate_server(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{self.base_url}/System/Info", headers=self._headers())
            response.raise_for_status()
            return response.json()

    async def authenticate(self, username: str, password: str) -> dict[str, Any]:
        payload = {"Username": username, "Pw": password}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{self.base_url}/Users/AuthenticateByName",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def refresh_library(self) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{self.base_url}/Library/Refresh", headers=self._headers())
            response.raise_for_status()

    async def wait_for_library_refresh(self, timeout_seconds: int = 300, poll_interval: float = 2.0) -> bool:
        """Wait for Jellyfin library refresh to complete.
        
        Polls the /System/Activities endpoint to check if a library scan is in progress.
        Returns True if scan completed, False if timed out.
        """
        end_time = asyncio.get_event_loop().time() + timeout_seconds
        async with httpx.AsyncClient(timeout=20) as client:
            while asyncio.get_event_loop().time() < end_time:
                try:
                    response = await client.get(
                        f"{self.base_url}/System/Activities",
                        headers=self._headers(),
                    )
                    response.raise_for_status()
                    activities = response.json().get("Activities", [])
                    # Check if any activity is a library scan
                    has_scan = any(
                        act.get("Type") == "LibraryRefresh" or "scan" in act.get("Name", "").lower()
                        for act in activities
                    )
                    if not has_scan:
                        log.info("Jellyfin library refresh completed")
                        return True
                except Exception:
                    log.debug("Could not poll library refresh status (may not be supported by this Jellyfin version)", exc_info=False)
                    # If polling doesn't work, just wait a bit anyway
                    await asyncio.sleep(poll_interval)
                    continue
                await asyncio.sleep(poll_interval)
        log.warning("Jellyfin library refresh timed out after %s seconds", timeout_seconds)
        return False

    # --- playlist management ---

    async def create_or_update_playlist(
        self, user_id: str, playlist_name: str, item_ids: list[str], playlist_id: str | None = None
    ) -> str:
        if not item_ids:
            return playlist_id or ""
        log.info(
            "Jellyfin playlist push: name=%s, items=%s, existing_id=%s",
            playlist_name,
            len(item_ids),
            playlist_id,
        )
        async with httpx.AsyncClient(timeout=60) as client:
            if playlist_id:
                await self._clear_playlist(client, playlist_id, user_id)
                resp = await client.post(
                    f"{self.base_url}/Playlists/{playlist_id}/Items",
                    params={"Ids": ",".join(item_ids), "UserId": user_id},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return playlist_id

            response = await client.post(
                f"{self.base_url}/Playlists",
                params={"Name": playlist_name, "UserId": user_id, "Ids": ",".join(item_ids)},
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
            return str(data["Id"])

    async def _clear_playlist(self, client: httpx.AsyncClient, playlist_id: str, user_id: str) -> None:
        """Remove all existing entries from a Jellyfin playlist so we can replace them in order."""
        try:
            response = await client.get(
                f"{self.base_url}/Playlists/{playlist_id}/Items",
                params={"UserId": user_id, "Limit": 10000},
                headers=self._headers(),
            )
            response.raise_for_status()
            items = response.json().get("Items", [])
            if not items:
                return
            entry_ids = [str(item["PlaylistItemId"]) for item in items if "PlaylistItemId" in item]
            if not entry_ids:
                entry_ids = [str(item["Id"]) for item in items]
            if entry_ids:
                del_resp = await client.delete(
                    f"{self.base_url}/Playlists/{playlist_id}/Items",
                    params={"EntryIds": ",".join(entry_ids)},
                    headers=self._headers(),
                )
                del_resp.raise_for_status()
        except Exception:
            log.warning("Could not clear playlist %s before update; items may duplicate", playlist_id, exc_info=True)

    # --- path → id resolution (ordered + paginated) ---

    async def resolve_item_ids_by_paths(self, user_id: str, file_paths: list[str]) -> list[str]:
        """Return Jellyfin item IDs in the same order as ``file_paths``, skipping unresolvable paths."""
        if not file_paths:
            return []
        path_to_id = await self._build_path_id_map(user_id)
        result: list[str] = []
        unresolved: list[str] = []
        for fp in file_paths:
            jf_id = path_to_id.get(fp.lower())
            if jf_id:
                result.append(jf_id)
            else:
                unresolved.append(fp)
        if unresolved:
            sample = unresolved[0]
            jf_sample = next(iter(path_to_id), "(empty map)")
            log.warning(
                "Jellyfin path resolution: %s/%s paths unresolved. Sample DB path: %s | Sample Jellyfin path: %s",
                len(unresolved),
                len(file_paths),
                sample,
                jf_sample,
            )
            # Enhanced debugging: show sample comparisons
            if path_to_id:
                log.debug(
                    "Path resolution debug: Input paths to resolve: %s",
                    [fp[:100] for fp in unresolved[:3]],
                )
                log.debug(
                    "Path resolution debug: First 5 Jellyfin paths in map: %s",
                    [p[:100] for p in list(path_to_id.keys())[:5]],
                )
        else:
            log.info("Jellyfin path resolution: all %s paths resolved", len(file_paths))
        return result

    async def _build_path_id_map(self, user_id: str) -> dict[str, str]:
        """Paginate ``/Users/{id}/Items`` and build a lowercased-path → id map."""
        path_map: dict[str, str] = {}
        start_index = 0
        page_size = 5000
        total_items = 0
        async with httpx.AsyncClient(timeout=60) as client:
            while True:
                response = await client.get(
                    f"{self.base_url}/Users/{user_id}/Items",
                    params={
                        "Recursive": "true",
                        "IncludeItemTypes": "Audio",
                        "Fields": "Path",
                        "Limit": page_size,
                        "StartIndex": start_index,
                    },
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
                items = data.get("Items", [])
                total_items = data.get("TotalRecordCount", 0)
                for item in items:
                    p = (item.get("Path") or "").lower()
                    if p:
                        path_map[p] = str(item["Id"])
                start_index += len(items)
                if start_index >= total_items or not items:
                    break
        log.debug(
            "Built Jellyfin path_id_map: %s total items in library, %s paths indexed",
            total_items,
            len(path_map),
        )
        if path_map:
            sample_paths = list(path_map.keys())[:3]
            log.debug("Sample Jellyfin paths in library: %s", sample_paths)
        return path_map
