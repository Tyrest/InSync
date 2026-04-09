import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "../api/client";
import { useAuthStore } from "../stores/authStore";

export function LoginPage(): JSX.Element {
  const navigate = useNavigate();
  const setToken = useAuthStore((s) => s.setToken);
  const refreshMe = useAuthStore((s) => s.refreshMe);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const response = await apiFetch<{ access_token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setToken(response.access_token);
      await refreshMe();
      navigate("/");
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="mx-auto mt-20 max-w-md rounded border border-zinc-800 bg-zinc-900 p-6">
      <h2 className="mb-4 text-xl font-semibold">Jellyfin Login</h2>
      <form className="space-y-3" onSubmit={onSubmit}>
        <input
          className="w-full rounded bg-zinc-800 p-2"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          className="w-full rounded bg-zinc-800 p-2"
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button className="w-full rounded bg-emerald-600 p-2 font-medium" type="submit">
          Sign In
        </button>
        {error && <p className="text-sm text-red-400">{error}</p>}
      </form>
    </div>
  );
}
