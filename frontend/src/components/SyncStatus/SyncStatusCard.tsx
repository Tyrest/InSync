import type { SyncStatus } from "../../types";

const QUEUE_ORDER = ["pending", "downloading", "completed", "failed"] as const;

type SyncStatusCardProps = {
  status: SyncStatus;
  active?: boolean;
};

function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function SyncStatusCard({ status, active = false }: SyncStatusCardProps): JSX.Element {
  const { download_total, download_done } = status;
  const fraction = download_total > 0 ? Math.min(1, download_done / download_total) : 0;
  const pct = Math.round(fraction * 100);

  return (
    <div className="rounded border border-zinc-800 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-zinc-200">Sync &amp; download queue</h3>
        {active ? (
          <span className="text-xs font-medium text-emerald-400">Live · updating</span>
        ) : (
          <span className="text-xs text-zinc-500">Latest snapshot</span>
        )}
      </div>
      <p className="mt-2 text-sm text-zinc-400">Last updated: {formatWhen(status.timestamp)}</p>
      <p className="mt-1 text-sm">Linked: {status.linked_platforms.join(", ") || "none"}</p>
      {status.next_sync && (
        <p className="mt-1 text-sm text-zinc-400">Next sync: {formatWhen(status.next_sync)}</p>
      )}

      {download_total > 0 && (
        <div className="mt-4">
          <div className="mb-1 flex justify-between text-xs text-zinc-400">
            <span>Downloads</span>
            <span>
              {download_done} / {download_total} ({pct}%)
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
            <div
              className="h-full rounded-full bg-emerald-600 transition-[width] duration-300 ease-out"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
        {QUEUE_ORDER.map((k) => (
          <div key={k} className="rounded bg-zinc-900 px-2 py-1">
            {k}: {status.queue[k] ?? 0}
          </div>
        ))}
      </div>
    </div>
  );
}
