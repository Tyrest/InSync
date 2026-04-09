import { Link, Outlet } from "react-router-dom";
import { useAuthStore } from "../../stores/authStore";

export function Layout(): JSX.Element {
  const me = useAuthStore((s) => s.me);
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto flex max-w-7xl">
        <aside className="w-64 border-r border-zinc-800 p-6">
          <h1 className="mb-6 text-xl font-bold">InSync</h1>
          <nav className="flex flex-col gap-3 text-sm">
            <Link to="/">Dashboard</Link>
            <Link to="/platforms">Platforms</Link>
            <Link to="/playlists">Playlists</Link>
            <Link to="/library">Library</Link>
            {me?.is_admin && <Link to="/admin">Admin</Link>}
          </nav>
        </aside>
        <main className="flex-1 p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
