import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../api/client";
import type { LibraryTracksResponse } from "../types";

const PAGE_SIZE = 100;

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ["KB", "MB", "GB"];
  let n = bytes / 1024;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // fallback: older browsers
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }
}

export function LibraryPage(): JSX.Element {
  const [data, setData] = useState<LibraryTracksResponse | null>(null);
  const [filterInput, setFilterInput] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });
    if (appliedQuery) {
      params.set("q", appliedQuery);
    }
    const response = await apiFetch<LibraryTracksResponse>(`/library/tracks?${params.toString()}`);
    setData(response);
  }, [appliedQuery, offset]);

  useEffect(() => {
    void load().catch((err: unknown) => {
      setError(err instanceof Error ? err.message : String(err));
    });
  }, [load]);

  function applySearch() {
    setAppliedQuery(filterInput.trim());
    setOffset(0);
  }

  function handleCopy(track: { id: number; file_path: string }) {
    void copyToClipboard(track.file_path).then(() => {
      setCopiedId(track.id);
      setTimeout(() => setCopiedId(null), 1500);
    });
  }

  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);
  const canPrev = offset > 0;
  const canNext = data !== null && offset + PAGE_SIZE < total;

  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Downloaded tracks</h2>
      <p className="text-sm text-zinc-400">
        Songs stored for your account (from playlists you sync). Search by title, artist, or album.
      </p>

      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          applySearch();
        }}
      >
        <input
          type="search"
          placeholder="Search…"
          value={filterInput}
          onChange={(e) => setFilterInput(e.target.value)}
          className="w-full max-w-md rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-zinc-500"
        />
        <button
          type="submit"
          className="rounded bg-zinc-700 px-3 py-2 text-sm hover:bg-zinc-600"
        >
          Search
        </button>
      </form>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {data && (
        <>
          <p className="text-sm text-zinc-500">
            {total === 0
              ? "No tracks yet — run a sync after linking platforms."
              : `Showing ${from}–${to} of ${total}`}
          </p>

          <div className="overflow-x-auto rounded border border-zinc-800">
            <table className="w-full min-w-[640px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-800 bg-zinc-900/80 text-xs uppercase tracking-wide text-zinc-500">
                  <th className="px-3 py-2 font-medium">Title</th>
                  <th className="px-3 py-2 font-medium">Artist</th>
                  <th className="px-3 py-2 font-medium">Album</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                  <th className="px-3 py-2 font-medium">Size</th>
                  <th className="px-3 py-2 font-medium">File</th>
                  <th className="px-3 py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {data.tracks.map((t) => (
                  <tr key={t.id} className="border-b border-zinc-800/80 hover:bg-zinc-900/50">
                    <td className="px-3 py-2 text-zinc-200">{t.title}</td>
                    <td className="px-3 py-2 text-zinc-300">{t.artist}</td>
                    <td className="px-3 py-2 text-zinc-400">{t.album}</td>
                    <td className="px-3 py-2 text-zinc-500">{t.source_platform}</td>
                    <td className="px-3 py-2 text-zinc-500">{formatBytes(t.file_size)}</td>
                    <td className="max-w-[200px] truncate px-3 py-2 font-mono text-xs text-zinc-500" title={t.file_path}>
                      {t.file_name}
                    </td>
                    <td className="px-2 py-2">
                      <button
                        type="button"
                        className="rounded px-2 py-0.5 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
                        title="Copy file path"
                        onClick={() => handleCopy(t)}
                      >
                        {copiedId === t.id ? "Copied" : "Copy path"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {total > PAGE_SIZE && (
            <div className="flex gap-2">
              <button
                type="button"
                disabled={!canPrev}
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                className="rounded border border-zinc-700 px-3 py-1.5 text-sm disabled:opacity-40"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={!canNext}
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
                className="rounded border border-zinc-700 px-3 py-1.5 text-sm disabled:opacity-40"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
