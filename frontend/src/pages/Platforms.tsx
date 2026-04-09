import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { apiFetch } from "../api/client";

type PlatformsResponse = {
  available: string[];
  linked: { platform: string; linked_at: string }[];
};

export function PlatformsPage(): JSX.Element {
  const location = useLocation();
  const [data, setData] = useState<PlatformsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [linking, setLinking] = useState<string | null>(null);

  const oauthStatus = useMemo(() => {
    const params = new URLSearchParams(location.search);
    const status = params.get("oauth_status");
    const platform = params.get("oauth_platform");
    const message = params.get("oauth_message");
    if (!status || !platform) {
      return null;
    }
    return { status, platform, message: message ?? "" };
  }, [location.search]);

  const linkedPlatforms = useMemo(
    () => new Set((data?.linked ?? []).map((l) => l.platform)),
    [data?.linked],
  );

  const load = useCallback(async () => {
    const response = await apiFetch<PlatformsResponse>("/platforms");
    setData(response);
  }, []);

  async function link(platform: string) {
    setError(null);
    setLinking(platform);
    try {
      const response = await apiFetch<{ authorize_url: string }>(`/platforms/${platform}/oauth/start`);
      window.location.href = response.authorize_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLinking(null);
    }
  }

  async function unlink(target: string) {
    await apiFetch(`/platforms/${target}/link`, { method: "DELETE" });
    await load();
  }

  useEffect(() => {
    void load();
  }, [load, location.pathname, location.search]);

  return (
    <section className="space-y-4">
      <h2 className="text-2xl font-semibold">Platforms</h2>
      {oauthStatus?.status === "success" && (
        <div className="rounded border border-emerald-700 bg-emerald-900/40 p-3 text-sm text-emerald-300">
          {oauthStatus.platform}: {oauthStatus.message || "Linked successfully"}
        </div>
      )}
      {oauthStatus?.status === "error" && (
        <div className="rounded border border-red-700 bg-red-900/40 p-3 text-sm text-red-300">
          {oauthStatus.platform}: {oauthStatus.message || "OAuth linking failed"}
        </div>
      )}
      {error && <div className="rounded bg-red-900/30 p-3 text-sm text-red-300">{error}</div>}
      <div className="rounded bg-zinc-900 p-4">
        <div className="mb-3 flex flex-wrap gap-3">
          {data?.available.map((name) => {
            const alreadyLinked = linkedPlatforms.has(name);
            return (
              <button
                key={name}
                type="button"
                className="rounded bg-blue-600 px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
                onClick={() => void link(name)}
                disabled={linking === name || alreadyLinked}
              >
                {alreadyLinked
                  ? `${name} linked`
                  : linking === name
                    ? `Connecting ${name}...`
                    : `Connect ${name}`}
              </button>
            );
          })}
        </div>
        <p className="text-sm text-zinc-400">
          Connect a provider you have not linked yet; use Unlink below to change accounts. OAuth will redirect
          you to approve access and return here automatically.
        </p>
      </div>
      <div className="space-y-2">
        {data?.linked.map((item) => (
          <div key={item.platform} className="flex items-center justify-between rounded bg-zinc-900 p-3">
            <span>{item.platform}</span>
            <button className="rounded bg-red-600 px-3 py-1" onClick={() => void unlink(item.platform)}>
              Unlink
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
