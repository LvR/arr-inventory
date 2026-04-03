import { CheckFilter, SortDirection, SortKey } from '../models/dashboard.models';

export const CHECK_RULE_KEYS: Array<{ key: string; label: string }> = [
  { key: 'downloads_matched', label: 'Downloads in torrents' },
  { key: 'movies_single_video_dir', label: 'Movies single video' },
  { key: 'movies_radarr_consistent', label: 'Movies match Radarr' },
  { key: 'tv_sonarr_consistent', label: 'TV match Sonarr' },
  { key: 'download_torrent_still_useful', label: 'Download torrent still useful' },
  { key: 'trackers_healthy', label: 'Trackers healthy' },
];

export const FILTER_STORAGE_KEY = 'arr-inventory.filters';
export const FILENAME_FILTER_DEBOUNCE_MS = 200;
export const DEFAULT_SORT_KEY: SortKey = 'group_key';
export const DEFAULT_SORT_DIRECTION: SortDirection = 'desc';

export function buildCheckFilters(): CheckFilter[] {
  return ['all', 'ok', 'ko', ...CHECK_RULE_KEYS.map((rule) => `ko:${rule.key}` as CheckFilter)];
}
