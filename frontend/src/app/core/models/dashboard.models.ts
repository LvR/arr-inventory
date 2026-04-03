export type SortDirection = 'asc' | 'desc';
export type FileFilter = 'all' | 'video' | 'audio' | 'other';
export type LocationFilter = 'all' | 'downloads' | 'movies' | 'radarr' | 'tv' | 'sonarr' | 'music';
export type CheckFilter = 'all' | 'ok' | 'ko' | `ko:${string}`;
export type CheckStatus = 'pending' | 'ok' | 'ko' | 'na';

export type SortKey =
  | 'consistency_status'
  | 'group_key'
  | 'hardlink_count'
  | 'size_bytes'
  | 'has_downloads'
  | 'has_movies'
  | 'has_radarr'
  | 'has_tv'
  | 'has_sonarr'
  | 'has_music'
  | 'torrent_count'
  | 'file_type'
  | 'filenames_display';

export interface Summary {
  files: number;
  downloads: number;
  movies: number;
  tv: number;
  music: number;
  torrents: number;
  groups: number;
  locations: number;
  checks_ok: number;
  checks_ko: number;
}

export interface JobState {
  job_key: string;
  label: string;
  state: string;
  progress: number;
  message: string;
  started_at_display?: string;
  updated_at_display?: string;
  duration_seconds?: number;
}

export interface Meta {
  last_inventory_at_display?: string;
  total_duration_seconds?: number;
}

export interface InventoryRow {
  id: number;
  consistency_status: CheckStatus;
  consistency_issue_count: number;
  group_key: string;
  device: number;
  inode: number;
  size_bytes: number;
  size_bytes_display: string;
  hardlink_count: number;
  location_count: number;
  filenames_display: string;
  has_downloads: number;
  has_movies: number;
  has_radarr: number;
  has_tv: number;
  has_sonarr: number;
  has_music: number;
  has_torrents: number;
  torrent_count: number;
  torrent_names: string[];
  torrents_tooltip: string;
  tracker_names: string[];
  check_results: Array<{ check_key: string; label: string; status: CheckStatus | string }>;
  file_type: FileFilter;
}

export interface DashboardResponse {
  settings?: {
    app_name?: string;
    data_root?: string;
  };
  summary: Summary;
  jobs: JobState[];
  inventory: InventoryRow[];
  meta: Meta;
  scan_job: JobState | null;
  filters?: {
    trackers?: string[];
  };
}

export interface UiTooltip {
  title: string;
  lines: string[];
  x: number;
  y: number;
}

export interface GroupDetail {
  id: number;
  consistency_status: CheckStatus;
  consistency_issue_count: number;
  group_key: string;
  device: number;
  inode: number;
  size_bytes: number;
  size_bytes_display: string;
  hardlink_count: number;
  filenames_display: string;
  path_groups: Array<{ label: string; entries: string[] }>;
  locations: Array<{
    id: number;
    root_bucket: string;
    path: string;
    filename: string;
    source: string;
    torrent_name: string;
    qbittorrent: { hash?: string; status?: string; category?: string; tags?: string };
    radarr: { items?: Array<Record<string, unknown>> };
    sonarr: { items?: Array<Record<string, unknown>> };
  }>;
  radarr: {
    imported: Array<{
      source: string;
      movie_id: number;
      title: string;
      year?: number;
      status: string;
      movie_path: string;
      file_path: string;
    }>;
    queue: Array<{
      source: string;
      movie_id: number;
      title: string;
      year?: number;
      status: string;
      movie_path: string;
      file_path: string;
      queue_id?: number;
      tracked_download_status?: string;
      tracked_download_state?: string;
      status_messages?: string[];
    }>;
  };
  sonarr: {
    imported: Array<{
      source: string;
      series_id: number;
      series_title: string;
      season_number?: number;
      episode_numbers?: number[];
      status: string;
      series_path: string;
      file_path: string;
    }>;
    queue: Array<{
      source: string;
      series_id: number;
      series_title: string;
      season_number?: number;
      episode_numbers?: number[];
      status: string;
      series_path: string;
      file_path: string;
      queue_id?: number;
      tracked_download_status?: string;
      tracked_download_state?: string;
      status_messages?: string[];
    }>;
  };
  torrents: Array<{
    hash: string;
    name: string;
    status: string;
    category: string;
    tags: string;
    total_uploaded: number;
    total_downloaded: number;
    ratio: number;
    seed_time: number;
    save_path: string;
    tracker_names: string[];
    trackers: Array<{ url: string; status: string; message: string; tracker_name?: string }>;
    files: Array<{ file_path: string; file_name: string; size_bytes: number; priority: number; progress: number; is_matched: number }>;
  }>;
  checks: Array<{ check_key: string; label: string; status: CheckStatus; summary: string; details: string[] }>;
}

export interface PersistedFilterState {
  q: string;
  check: CheckFilter;
  tracker: string;
  location: LocationFilter;
  type: FileFilter;
  sort: SortKey;
  direction: SortDirection;
}
