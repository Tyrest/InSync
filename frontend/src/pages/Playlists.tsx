import { useEffect, useState } from "react";
import { apiFetch, formatApiError } from "../api/client";

type ApiPlaylist = {
  id: number;
  platform: string;
  name: string;
  enabled: boolean;
  last_synced: string | null;
};

export function PlaylistsPage(): JSX.Element {
  const [items, setItems] = useState<ApiPlaylist[]>([]);
  const [syncingId, setSyncingId] = useState<number | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  async function load() {
    const response = await apiFetch<{ playlists: ApiPlaylist[] }>("/playlists");
    setItems(response.playlists);
  }

  async function toggle(id: number, enabled: boolean) {
    await apiFetch(`/playlists/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
    await load();
  }

  async function syncOne(id: number) {
    setBanner(null);
    setSyncingId(id);
    try {
      await apiFetch(`/playlists/${id}/sync`, { method: "POST" });
      setBanner({ kind: "ok", text: "Sync started for this playlist." });
    } catch (err) {
      setBanner({ kind: "err", text: formatApiError(err) });
    } finally {
      setSyncingId(null);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Playlists</h2>
      <p className="text-sm text-zinc-400">
        Toggle which upstream playlists should be mirrored into Jellyfin, or sync an individual playlist.
      </p>
      {banner && (
        <p
          className={
            banner.kind === "ok"
              ? "rounded border border-emerald-800 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-200"
              : "rounded border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-200"
          }
          role="status"
        >
          {banner.text}
        </p>
      )}
      <div className="space-y-2">
        {items.map((item) => (
          <div key={item.id} className="flex items-center gap-3 rounded bg-zinc-900 p-3">
            <label className="flex flex-1 items-center gap-2">
              <input
                type="checkbox"
                checked={item.enabled}
                onChange={(event) => void toggle(item.id, event.target.checked)}
              />
              <span>
                {item.platform}: {item.name}
              </span>
              {item.last_synced && (
                <span className="ml-auto text-xs text-zinc-500">
                  Last: {new Date(item.last_synced).toLocaleString()}
                </span>
              )}
            </label>
            <button
              type="button"
              className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={syncingId === item.id || !item.enabled}
              onClick={() => void syncOne(item.id)}
            >
              {syncingId === item.id ? "Syncing…" : "Sync"}
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
