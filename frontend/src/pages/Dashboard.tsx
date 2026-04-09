import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { apiFetch, formatApiError } from "../api/client";
import { SyncStatusCard } from "../components/SyncStatus/SyncStatusCard";
import type { DashboardSummary, DownloadFailuresResponse, SyncStatus } from "../types";

const FAILURE_PAGE_SIZE = 30;

function formatWhen(iso: string | null): string {
  if (!iso) {
    return "—";
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return iso;
  }
  return d.toLocaleString();
}

export function DashboardPage(): JSX.Element {
  const location = useLocation();
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [failures, setFailures] = useState<DownloadFailuresResponse | null>(null);
  const [failurePage, setFailurePage] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const loadCore = useCallback(async () => {
    const [s, sum] = await Promise.all([
      apiFetch<SyncStatus>("/sync/status"),
      apiFetch<DashboardSummary>("/dashboard/summary"),
    ]);
    setStatus(s);
    setSummary(sum);
  }, []);

  const loadFailures = useCallback(async (page: number) => {
    const offset = page * FAILURE_PAGE_SIZE;
    const f = await apiFetch<DownloadFailuresResponse>(
      `/sync/download-failures?limit=${FAILURE_PAGE_SIZE}&offset=${offset}`,
    );
    setFailures(f);
    setFailurePage(page);
  }, []);

  const load = useCallback(async () => {
    await Promise.all([loadCore(), loadFailures(failurePage)]);
  }, [loadCore, loadFailures, failurePage]);

  useEffect(() => {
    void loadCore();
  }, [loadCore, location.pathname]);

  useEffect(() => {
    void loadFailures(failurePage);
  }, [loadFailures, failurePage, location.pathname]);

  useEffect(() => {
    if (failures == null || failures.total === 0) {
      return;
    }
    const maxPage = Math.max(0, Math.ceil(failures.total / FAILURE_PAGE_SIZE) - 1);
    if (failurePage > maxPage) {
      setFailurePage(maxPage);
    }
  }, [failures?.total, failurePage, failures]);

  async function manualSync() {
    setBanner(null);
    setSyncing(true);
    try {
      await apiFetch<{ status: string }>("/sync/manual", { method: "POST" });
      setBanner({ kind: "ok", text: "Sync started. The dashboard will update as downloads finish." });
    } catch (err) {
      setBanner({ kind: "err", text: formatApiError(err) });
      setSyncing(false);
    }
  }

  const pollActive = syncing || Boolean(status?.sync_running);
  useEffect(() => {
    if (!pollActive) {
      if (syncing) {
        setSyncing(false);
        setBanner({ kind: "ok", text: "Sync finished." });
      }
      return;
    }
    void loadCore();
    void loadFailures(failurePage);
    const id = window.setInterval(() => {
      void loadCore();
      void loadFailures(failurePage);
    }, 900);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollActive, loadCore, loadFailures, failurePage]);

  const syncUiActive = syncing || Boolean(status?.sync_running);
  const noPlatforms = summary != null && summary.platform_links === 0;
  const noPlaylists = summary != null && summary.synced_playlists_total === 0;
  const syncDisabled = syncing || noPlatforms;
  const failureTotal = failures?.total ?? 0;
  const failureTotalPages = Math.max(1, Math.ceil(failureTotal / FAILURE_PAGE_SIZE));

  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Dashboard</h2>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="rounded bg-emerald-600 px-4 py-2 disabled:cursor-not-allowed disabled:opacity-60"
          disabled={syncDisabled}
          onClick={() => void manualSync()}
          title={noPlatforms ? "Link a platform first" : noPlaylists ? "No playlists discovered yet" : undefined}
        >
          {syncing ? "Syncing…" : "Sync Now"}
        </button>
        {noPlatforms && !syncUiActive && (
          <span className="text-sm text-zinc-500">Link a platform to enable syncing</span>
        )}
        {syncUiActive && (
          <span className="text-sm text-zinc-400">Running playlist sync and downloads…</span>
        )}
      </div>
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

      {summary && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Tracks in library</p>
            <p className="mt-1 text-2xl font-semibold text-zinc-100">{summary.tracks_in_library}</p>
            <p className="mt-1 text-xs text-zinc-500">On your synced playlists</p>
          </div>
          <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Synced playlists</p>
            <p className="mt-1 text-2xl font-semibold text-zinc-100">
              {summary.synced_playlists_enabled}
              <span className="text-lg font-normal text-zinc-500">
                {" "}
                / {summary.synced_playlists_total}
              </span>
            </p>
            <p className="mt-1 text-xs text-zinc-500">Enabled / total</p>
          </div>
          <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Platform links</p>
            <p className="mt-1 text-2xl font-semibold text-zinc-100">{summary.platform_links}</p>
            <p className="mt-1 text-xs text-zinc-500">Connected sources</p>
          </div>
          <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Next scheduled sync</p>
            <p className="mt-1 text-sm font-medium text-zinc-200">
              {formatWhen(summary.next_sync)}
            </p>
            <p className="mt-1 text-xs text-zinc-500">
              Last download: {formatWhen(summary.last_completed_download)}
            </p>
          </div>
        </div>
      )}

      {status && <SyncStatusCard status={status} active={syncUiActive} />}

      {failureTotal > 0 && failures && (
        <div className="rounded border border-zinc-800 p-4">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h3 className="text-sm font-medium text-zinc-300">Download failures</h3>
              <p className="mt-1 text-xs text-zinc-500">
                Individual tracks can fail while the rest of the sync succeeds (e.g. YouTube unavailable).{" "}
                {failureTotal} total.
              </p>
            </div>
            {failureTotalPages > 1 && (
              <div className="flex items-center gap-2 text-sm">
                <button
                  type="button"
                  className="rounded border border-zinc-700 px-2 py-1 text-zinc-300 disabled:cursor-not-allowed disabled:opacity-40"
                  disabled={failurePage <= 0}
                  onClick={() => setFailurePage((p) => Math.max(0, p - 1))}
                >
                  Previous
                </button>
                <span className="text-xs text-zinc-500">
                  Page {failurePage + 1} / {failureTotalPages}
                </span>
                <button
                  type="button"
                  className="rounded border border-zinc-700 px-2 py-1 text-zinc-300 disabled:cursor-not-allowed disabled:opacity-40"
                  disabled={failurePage >= failureTotalPages - 1}
                  onClick={() => setFailurePage((p) => Math.min(failureTotalPages - 1, p + 1))}
                >
                  Next
                </button>
              </div>
            )}
          </div>
          <div className="mt-3 max-h-[min(28rem,55vh)] space-y-2 overflow-y-auto pr-1 text-sm">
            {failures.failures.map((d, i) => (
              <div
                key={`${d.completed_at ?? d.created_at}-${d.title}-${i}`}
                className="rounded bg-zinc-900/80 px-2 py-1.5"
              >
                <span className="text-zinc-300">
                  {d.title} — {d.artist}
                </span>
                <span className="mt-1 block whitespace-pre-wrap text-xs text-zinc-500">
                  {d.error_message || "(no error message)"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
