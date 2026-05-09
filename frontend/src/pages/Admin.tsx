import { useEffect, useState } from "react";
import { apiFetch } from "../api/client";

type User = { id: number; username: string; is_admin: boolean };
type EffectiveSettings = {
  values: Record<string, string | null>;
  sources: Record<string, string>;
  configured: { spotify: boolean; youtube: boolean };
};

export function AdminPage(): JSX.Element {
  const [users, setUsers] = useState<User[]>([]);
  const [system, setSystem] = useState<Record<string, unknown>>({});
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [effective, setEffective] = useState<EffectiveSettings | null>(null);
  const [concurrency, setConcurrency] = useState("3");
  const [syncHour, setSyncHour] = useState("2");
  const [spotifyClientId, setSpotifyClientId] = useState("");
  const [spotifyClientSecret, setSpotifyClientSecret] = useState("");
  const [googleClientId, setGoogleClientId] = useState("");
  const [googleClientSecret, setGoogleClientSecret] = useState("");
  const [oauthRedirectBaseUrl, setOauthRedirectBaseUrl] = useState("");
  const [serverTimezone, setServerTimezone] = useState("");
  const [audioFormat, setAudioFormat] = useState("opus");
  const [audioQuality, setAudioQuality] = useState("128");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [webhookEvents, setWebhookEvents] = useState("sync_complete,sync_failed");

  async function load() {
    const u = await apiFetch<{ users: User[] }>("/admin/users");
    const s = await apiFetch<Record<string, unknown>>("/admin/system");
    const cfg = await apiFetch<Record<string, string>>("/admin/settings");
    const eff = await apiFetch<EffectiveSettings>("/admin/settings/effective");
    setUsers(u.users);
    setSystem(s);
    setSettings(cfg);
    setEffective(eff);
    setConcurrency(cfg.download_concurrency ?? "3");
    setSyncHour(cfg.sync_hour ?? "2");
    setSpotifyClientId(cfg.spotify_client_id ?? "");
    // Secret fields are never pre-filled — the API returns masked values and we
    // don't want to round-trip them back. Leave blank; placeholder shows status.
    setSpotifyClientSecret("");
    setGoogleClientId(cfg.google_client_id ?? "");
    setGoogleClientSecret("");
    setOauthRedirectBaseUrl(cfg.oauth_redirect_base_url ?? "");
    setServerTimezone(cfg.server_timezone ?? "");
    setAudioFormat(cfg.audio_format ?? "opus");
    setAudioQuality(cfg.audio_quality ?? "128");
    setWebhookUrl(cfg.webhook_url ?? "");
    setWebhookSecret("");
    setWebhookEvents(cfg.webhook_events ?? "sync_complete,sync_failed");
  }

  async function unsetSecret(key: string) {
    await apiFetch(`/admin/settings/${key}`, { method: "DELETE" });
    await load();
  }

  async function save() {
    const payload: Record<string, unknown> = {
      download_concurrency: Number(concurrency),
      sync_hour: Number(syncHour),
      spotify_client_id: spotifyClientId || undefined,
      spotify_client_secret: spotifyClientSecret || undefined,
      google_client_id: googleClientId || undefined,
      google_client_secret: googleClientSecret || undefined,
      oauth_redirect_base_url: oauthRedirectBaseUrl || undefined,
      server_timezone: serverTimezone || undefined,
      audio_format: audioFormat || undefined,
      audio_quality: audioQuality || undefined,
      webhook_url: webhookUrl || undefined,
      webhook_secret: webhookSecret || undefined,
      webhook_events: webhookEvents || undefined,
    };
    // Strip undefined so backend doesn't receive null
    for (const key of Object.keys(payload)) {
      if (payload[key] === undefined) delete payload[key];
    }
    await apiFetch("/admin/settings", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    await load();
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <section className="space-y-6">
      <h2 className="text-2xl font-semibold">Admin</h2>

      {/* General settings */}
      <div className="rounded bg-zinc-900 p-4">
        <h3 className="mb-2 font-medium">Settings</h3>
        <div className="mb-3 grid grid-cols-2 gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span>Download concurrency</span>
            <input className="rounded bg-zinc-800 p-2" value={concurrency} onChange={(e) => setConcurrency(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span>Sync hour (server TZ)</span>
            <input className="rounded bg-zinc-800 p-2" value={syncHour} onChange={(e) => setSyncHour(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span>Server timezone (IANA)</span>
            <input className="rounded bg-zinc-800 p-2" placeholder="America/Chicago" value={serverTimezone} onChange={(e) => setServerTimezone(e.target.value)} />
          </label>
        </div>

        {/* Audio quality */}
        <h4 className="mb-2 mt-4 font-medium">Audio Quality</h4>
        <div className="mb-3 grid grid-cols-2 gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span>Format</span>
            <select className="rounded bg-zinc-800 p-2" value={audioFormat} onChange={(e) => setAudioFormat(e.target.value)}>
              <option value="opus">Opus (default)</option>
              <option value="mp3">MP3</option>
              <option value="flac">FLAC (lossless)</option>
              <option value="m4a">M4A / AAC</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span>Quality / bitrate</span>
            <select className="rounded bg-zinc-800 p-2" value={audioQuality} onChange={(e) => setAudioQuality(e.target.value)}>
              <option value="128">128 kbps (default Opus)</option>
              <option value="160">160 kbps</option>
              <option value="192">192 kbps</option>
              <option value="256">256 kbps</option>
              <option value="320">320 kbps (best MP3)</option>
              <option value="0">Best (lossless formats)</option>
            </select>
          </label>
        </div>

        {/* OAuth providers */}
        <h4 className="mb-2 mt-4 font-medium">OAuth Providers</h4>
        <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
          <label className="flex flex-col gap-1">
            <span>Spotify Client ID</span>
            <input className="rounded bg-zinc-800 p-2" value={spotifyClientId} onChange={(e) => setSpotifyClientId(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span>Spotify Client Secret</span>
            <div className="flex gap-2">
              <input className="flex-1 rounded bg-zinc-800 p-2" type="password" placeholder={settings.spotify_client_secret ? "leave blank to keep existing" : "not set"} value={spotifyClientSecret} onChange={(e) => setSpotifyClientSecret(e.target.value)} />
              {settings.spotify_client_secret && (
                <button className="rounded bg-zinc-700 px-2 py-1 text-xs hover:bg-red-700" onClick={() => void unsetSecret("spotify_client_secret")}>Unset</button>
              )}
            </div>
          </label>
          <label className="flex flex-col gap-1">
            <span>Google Client ID</span>
            <input className="rounded bg-zinc-800 p-2" value={googleClientId} onChange={(e) => setGoogleClientId(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span>Google Client Secret</span>
            <div className="flex gap-2">
              <input className="flex-1 rounded bg-zinc-800 p-2" type="password" placeholder={settings.google_client_secret ? "leave blank to keep existing" : "not set"} value={googleClientSecret} onChange={(e) => setGoogleClientSecret(e.target.value)} />
              {settings.google_client_secret && (
                <button className="rounded bg-zinc-700 px-2 py-1 text-xs hover:bg-red-700" onClick={() => void unsetSecret("google_client_secret")}>Unset</button>
              )}
            </div>
          </label>
          <label className="flex flex-col gap-1 md:col-span-2">
            <span>OAuth Redirect Base URL (optional)</span>
            <input className="rounded bg-zinc-800 p-2" placeholder="https://my.domain/insync" value={oauthRedirectBaseUrl} onChange={(e) => setOauthRedirectBaseUrl(e.target.value)} />
          </label>
        </div>

        {/* Webhooks */}
        <h4 className="mb-2 mt-4 font-medium">Webhooks</h4>
        <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
          <label className="flex flex-col gap-1 md:col-span-2">
            <span>Webhook URL</span>
            <input className="rounded bg-zinc-800 p-2" placeholder="https://example.com/webhook" value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span>Webhook Secret</span>
            <div className="flex gap-2">
              <input className="flex-1 rounded bg-zinc-800 p-2" type="password" placeholder={settings.webhook_secret ? "leave blank to keep existing" : "not set"} value={webhookSecret} onChange={(e) => setWebhookSecret(e.target.value)} />
              {settings.webhook_secret && (
                <button className="rounded bg-zinc-700 px-2 py-1 text-xs hover:bg-red-700" onClick={() => void unsetSecret("webhook_secret")}>Unset</button>
              )}
            </div>
          </label>
          <label className="flex flex-col gap-1">
            <span>Events (comma-separated)</span>
            <input className="rounded bg-zinc-800 p-2" placeholder="sync_complete,sync_failed" value={webhookEvents} onChange={(e) => setWebhookEvents(e.target.value)} />
          </label>
        </div>

        <button className="mt-4 rounded bg-emerald-600 px-3 py-1" onClick={() => void save()}>
          Save settings
        </button>

        {effective && (
          <div className="mt-3 rounded bg-zinc-800 p-3 text-xs">
            <p>Spotify configured: {effective.configured.spotify ? "yes" : "no"}</p>
            <p>YouTube configured: {effective.configured.youtube ? "yes" : "no"}</p>
            <p>Spotify source: {effective.sources.spotify_client_id}</p>
            <p>Google source: {effective.sources.google_client_id}</p>
            {effective.values.audio_format && <p>Audio: {effective.values.audio_format} @ {effective.values.audio_quality}</p>}
            {effective.values.server_timezone && <p>Timezone: {effective.values.server_timezone}</p>}
          </div>
        )}
      </div>

      {/* Users */}
      <div className="rounded bg-zinc-900 p-4">
        <h3 className="mb-2 font-medium">Users</h3>
        <ul className="space-y-2 text-sm">
          {users.map((u) => (
            <li key={u.id}>
              {u.username} {u.is_admin ? "(admin)" : ""}
            </li>
          ))}
        </ul>
      </div>

      {/* System */}
      <div className="rounded bg-zinc-900 p-4">
        <h3 className="mb-2 font-medium">System</h3>
        <pre className="text-xs text-zinc-300">{JSON.stringify(system, null, 2)}</pre>
      </div>
    </section>
  );
}
