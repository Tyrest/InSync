export type MeResponse = {
  id: string;
  jellyfin_user_id: string;
  username: string;
  is_admin: boolean;
};

export type SyncStatus = {
  linked_platforms: string[];
  queue: Record<string, number>;
  sync_running: boolean;
  download_total: number;
  download_done: number;
  timestamp: string;
  next_sync: string | null;
};

export type SyncHistoryDownload = {
  title: string;
  artist: string;
  status: string;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
};

export type SyncHistory = {
  last_completed_download: string | null;
  recent_downloads: SyncHistoryDownload[];
};

export type DashboardSummary = {
  tracks_in_library: number;
  synced_playlists_total: number;
  synced_playlists_enabled: number;
  platform_links: number;
  last_completed_download: string | null;
  next_sync: string | null;
};

export type DownloadFailuresResponse = {
  total: number;
  limit: number;
  offset: number;
  failures: SyncHistoryDownload[];
};

export type LibraryTrack = {
  id: number;
  title: string;
  artist: string;
  album: string;
  duration_seconds: number;
  source_platform: string;
  source_id: string;
  file_size: number;
  file_name: string;
  file_path: string;
  created_at: string;
};

export type LibraryTracksResponse = {
  total: number;
  limit: number;
  offset: number;
  tracks: LibraryTrack[];
};
