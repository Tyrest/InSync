import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../api/client";

type SetupPageProps = {
  onConfigured?: () => void;
};

export function SetupPage({ onConfigured }: SetupPageProps): JSX.Element {
  const navigate = useNavigate();
  const [jellyfinUrl, setJellyfinUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await apiFetch("/setup", {
        method: "POST",
        body: JSON.stringify({ jellyfin_url: jellyfinUrl, jellyfin_api_key: apiKey }),
      });
      onConfigured?.();
      navigate("/login", { replace: true });
    } catch (err) {
      const rawMessage = err instanceof Error ? err.message : String(err);
      try {
        const parsed = JSON.parse(rawMessage) as { detail?: string };
        setError(parsed.detail ?? rawMessage);
      } catch {
        setError(rawMessage);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto mt-20 max-w-2xl rounded border border-zinc-800 bg-zinc-900 p-6">
      <h2 className="mb-2 text-2xl font-semibold">First-run Setup</h2>
      <p className="mb-4 text-sm text-zinc-400">Configure Jellyfin server integration.</p>
      <form className="space-y-3" onSubmit={onSubmit}>
        <input
          className="w-full rounded bg-zinc-800 p-2"
          placeholder="https://jellyfin.example.com"
          value={jellyfinUrl}
          onChange={(e) => setJellyfinUrl(e.target.value)}
        />
        <input
          className="w-full rounded bg-zinc-800 p-2"
          placeholder="Jellyfin API Key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
        <button
          className="rounded bg-blue-600 px-4 py-2 font-medium disabled:cursor-not-allowed disabled:opacity-50"
          type="submit"
          disabled={saving}
        >
          {saving ? "Saving..." : "Save Setup"}
        </button>
      </form>
      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
    </div>
  );
}
