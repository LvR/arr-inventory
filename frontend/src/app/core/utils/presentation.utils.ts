import { CHECK_RULE_KEYS } from '../constants/inventory.constants';
import {
  TORRENT_STATUS_CLASSES,
  TORRENT_STATUS_LABELS,
  TRACKER_STATUS_CLASSES,
  TRACKER_STATUS_LABELS,
} from '../constants/status.constants';
import { CheckFilter, CheckStatus, FileFilter, InventoryRow, JobState, LocationFilter } from '../models/dashboard.models';

export function statusLabel(state: string | undefined): string {
  if (state === 'queued') return 'Pending';
  if (state === 'running') return 'Running';
  if (state === 'done') return 'Done';
  if (state === 'cancelled') return 'Canceled';
  if (state === 'error') return 'Done';
  return 'Idle';
}

export function checkFilterLabel(filter: CheckFilter): string {
  if (filter === 'all') return 'All';
  if (filter.startsWith('ko:')) {
    const ruleKey = filter.slice(3);
    return CHECK_RULE_KEYS.find((rule) => rule.key === ruleKey)?.label ?? ruleKey;
  }
  return filter.toUpperCase();
}

export function locationFilterLabel(filter: LocationFilter): string {
  if (filter === 'all') return 'All';
  if (filter === 'radarr') return 'Radarr';
  if (filter === 'sonarr') return 'Sonarr';
  if (filter === 'tv') return 'TV';
  return filter.charAt(0).toUpperCase() + filter.slice(1);
}

export function fileFilterLabel(filter: FileFilter): string {
  return filter === 'all' ? 'All' : filter.charAt(0).toUpperCase() + filter.slice(1);
}

export function fileTypeBadgeClass(fileType: FileFilter): string {
  return `type-badge type-badge--${fileType}`;
}

export function consistencyBadgeClass(status: CheckStatus): string {
  return `check-badge check-badge--${status}`;
}

export function consistencyBadgeLabel(status: CheckStatus): string {
  if (status === 'ok') return '✓';
  if (status === 'ko') return '!';
  if (status === 'na') return 'N/A';
  return '?';
}

export function checkResultClass(status: CheckStatus): string {
  return status === 'na' ? 'check-result check-result--na' : 'check-result';
}

export function torrentBadge(row: InventoryRow): string {
  return row.torrent_count > 0 ? String(row.torrent_count) : '—';
}

export function checkTooltipLines(row: InventoryRow): string[] {
  return (row.check_results ?? [])
    .filter((check) => check.status !== 'na')
    .map((check) => `${consistencyBadgeLabel(check.status as CheckStatus)} ${check.label}`);
}

export function jobHelpLines(jobKey: string): string[] {
  if (jobKey === 'filesystem-scan') {
    return ['Scans /data roots and rebuilds hardlink groups.'];
  }
  if (jobKey === 'qbittorrent-sync') {
    return ['Loads qBittorrent torrents, trackers, and file matches.'];
  }
  if (jobKey === 'radarr-sync') {
    return ['Loads Radarr movies and queue items, then matches them to indexed files.'];
  }
  if (jobKey === 'sonarr-sync') {
    return ['Loads Sonarr episode files and queue items, then matches them to indexed files.'];
  }
  if (jobKey === 'consistency-check') {
    return [
      'Downloads in torrents: every downloads file must match a torrent.',
      'Movies single video directory: a movies folder must not contain two videos from the same group.',
      'Movies match Radarr: movies files and imported Radarr entries must match each other.',
      'TV match Sonarr: TV files and imported Sonarr entries must match each other.',
      'Download torrent still useful: downloads-only groups become KO only when all matched torrents exceed the configured seed time and ratio thresholds.',
      'Trackers healthy: no active tracker should report an error.',
    ];
  }
  return ['No description available.'];
}

export function formatSeconds(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function jobDuration(job: JobState): string {
  return `${formatSeconds(job.duration_seconds ?? 0)}s`;
}

export function totalDuration(value: number): string {
  return `${formatSeconds(value)}s`;
}

export function trackerNamesLine(trackerNames: string[]): string {
  return trackerNames.length ? trackerNames.join(', ') : '—';
}

export function torrentStatusLabel(status: string): string {
  const normalized = status.trim();
  const key = normalized.toLowerCase();
  return (TORRENT_STATUS_LABELS[key] ?? normalized) || 'Unknown';
}

export function torrentStatusClass(status: string): string {
  const normalized = status.trim().toLowerCase();
  return TORRENT_STATUS_CLASSES[normalized] ?? 'state-badge state-badge--idle';
}

export function trackerStatusLabel(status: string): string {
  const normalized = status.trim().toLowerCase();
  return (TRACKER_STATUS_LABELS[normalized] ?? status) || 'Unknown';
}

export function trackerStatusClass(status: string): string {
  const normalized = status.trim().toLowerCase();
  return TRACKER_STATUS_CLASSES[normalized] ?? 'state-badge state-badge--idle';
}

export function humanBytes(value: number): string {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return unitIndex === 0 ? `${Math.round(size)} ${units[unitIndex]}` : `${size.toFixed(1)} ${units[unitIndex]}`;
}

export function humanSeconds(value: number): string {
  const total = Math.max(0, Math.round(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}
