import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { apiFetch } from "./api/client";
import { Layout } from "./components/Layout/Layout";
import { useAuthStore } from "./stores/authStore";
import { AdminPage } from "./pages/Admin";
import { DashboardPage } from "./pages/Dashboard";
import { LoginPage } from "./pages/Login";
import { PlatformsPage } from "./pages/Platforms";
import { LibraryPage } from "./pages/Library";
import { PlaylistsPage } from "./pages/Playlists";
import { SetupPage } from "./pages/Setup";

function RequireAuth({ children }: { children: JSX.Element }): JSX.Element {
  const token = useAuthStore((s) => s.token);
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

export default function App(): JSX.Element {
  const token = useAuthStore((s) => s.token);
  const refreshMe = useAuthStore((s) => s.refreshMe);
  const me = useAuthStore((s) => s.me);
  const [configured, setConfigured] = useState<boolean | null>(null);

  useEffect(() => {
    void (async () => {
      const response = await apiFetch<{ isConfigured: boolean }>("/config/client");
      setConfigured(response.isConfigured);
    })();
  }, []);

  useEffect(() => {
    if (token) {
      void refreshMe().catch(() => {
        /* 401 handled in apiFetch (redirect to login); ignore rejection */
      });
    }
  }, [token, refreshMe]);

  if (configured === false) {
    return <SetupPage onConfigured={() => setConfigured(true)} />;
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="platforms" element={<PlatformsPage />} />
        <Route path="playlists" element={<PlaylistsPage />} />
        <Route path="library" element={<LibraryPage />} />
        <Route path="admin" element={me?.is_admin ? <AdminPage /> : <Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
