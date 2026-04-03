import { computed, DestroyRef, effect, Injectable, signal } from '@angular/core';

import {
  buildCheckFilters,
  CHECK_RULE_KEYS,
  DEFAULT_SORT_DIRECTION,
  DEFAULT_SORT_KEY,
  FILENAME_FILTER_DEBOUNCE_MS,
  FILTER_STORAGE_KEY,
} from '../constants/inventory.constants';
import {
  CheckFilter,
  FileFilter,
  InventoryRow,
  LocationFilter,
  PersistedFilterState,
  SortDirection,
  SortKey,
} from '../models/dashboard.models';
import { checkFilterLabel, fileFilterLabel, humanBytes, locationFilterLabel } from '../utils/presentation.utils';

@Injectable({ providedIn: 'root' })
export class InventoryStateService {
  readonly sortKey = signal<SortKey>(DEFAULT_SORT_KEY);
  readonly sortDirection = signal<SortDirection>(DEFAULT_SORT_DIRECTION);
  readonly filenameQuery = signal('');
  readonly debouncedFilenameQuery = signal('');
  readonly checkFilter = signal<CheckFilter>('all');
  readonly trackerFilter = signal('all');
  readonly locationFilter = signal<LocationFilter>('all');
  readonly fileFilter = signal<FileFilter>('all');
  readonly availableTrackers = signal<string[]>([]);
  readonly inventory = signal<InventoryRow[]>([]);

  readonly tableHeaders: Array<{ key: SortKey; label: string }> = [
    { key: 'consistency_status', label: 'Check' },
    { key: 'group_key', label: 'ID' },
    { key: 'hardlink_count', label: 'HL' },
    { key: 'has_downloads', label: 'Downloads' },
    { key: 'torrent_count', label: 'Torrents' },
    { key: 'has_movies', label: 'Movies' },
    { key: 'has_radarr', label: 'Radarr' },
    { key: 'has_tv', label: 'TV' },
    { key: 'has_sonarr', label: 'Sonarr' },
    { key: 'has_music', label: 'Music' },
    { key: 'filenames_display', label: 'Files' },
    { key: 'size_bytes', label: 'Size' },
    { key: 'file_type', label: 'Type' },
  ];
  readonly checkFilters: CheckFilter[] = buildCheckFilters();
  readonly checkGlobalFilters: CheckFilter[] = ['all', 'ok', 'ko'];
  readonly checkRuleFilters: CheckFilter[] = CHECK_RULE_KEYS.map((rule) => `ko:${rule.key}` as CheckFilter);
  readonly locationFilters: LocationFilter[] = ['all', 'downloads', 'movies', 'radarr', 'tv', 'sonarr', 'music'];
  readonly fileFilters: FileFilter[] = ['all', 'video', 'audio', 'other'];

  private filenameQueryDebounceHandle: ReturnType<typeof setTimeout> | null = null;

  private readonly searchFilteredInventory = computed(() => {
    const queryTokens = this.filenameQueryTokens();
    return this.inventory().filter((row) => this.matchesFilenameQuery(row, queryTokens));
  });

  readonly sortedInventory = computed(() => {
    const key = this.sortKey();
    const direction = this.sortDirection();
    const currentCheckFilter = this.checkFilter();
    const currentTrackerFilter = this.trackerFilter();
    const currentLocationFilter = this.locationFilter();
    const currentFileFilter = this.fileFilter();
    const rows = this.searchFilteredInventory().filter(
      (row) =>
        this.matchesCheckFilter(row, currentCheckFilter) &&
        this.matchesTrackerFilter(row, currentTrackerFilter) &&
        this.matchesLocationFilter(row, currentLocationFilter) &&
        (currentFileFilter === 'all' || row.file_type === currentFileFilter),
    );
    rows.sort((left, right) => {
      const comparison = this.compareValues(left[key], right[key]);
      return direction === 'asc' ? comparison : -comparison;
    });
    return rows;
  });

  readonly filteredTotalSizeBytes = computed(() => this.sortedInventory().reduce((total, row) => total + row.size_bytes, 0));
  readonly filteredTotalSizeDisplay = computed(() => humanBytes(this.filteredTotalSizeBytes()));

  readonly checkFilterCounts = computed<Record<CheckFilter, number>>(() => {
    const rows = this.searchFilteredInventory().filter(
      (row) =>
        this.matchesTrackerFilter(row, this.trackerFilter()) &&
        this.matchesLocationFilter(row, this.locationFilter()) &&
        (this.fileFilter() === 'all' || row.file_type === this.fileFilter()),
    );
    const counts: Record<string, number> = {
      all: rows.length,
      ok: rows.filter((row) => row.consistency_status === 'ok').length,
      ko: rows.filter((row) => row.consistency_status === 'ko').length,
    };
    for (const rule of CHECK_RULE_KEYS) {
      counts[`ko:${rule.key}`] = rows.filter((row) =>
        (row.check_results ?? []).some((check) => check.check_key === rule.key && check.status === 'ko'),
      ).length;
    }
    return counts as Record<CheckFilter, number>;
  });

  readonly locationFilterCounts = computed<Record<LocationFilter, number>>(() => {
    const rows = this.searchFilteredInventory().filter(
      (row) =>
        this.matchesCheckFilter(row, this.checkFilter()) &&
        this.matchesTrackerFilter(row, this.trackerFilter()) &&
        (this.fileFilter() === 'all' || row.file_type === this.fileFilter()),
    );
    return {
      all: rows.length,
      downloads: rows.filter((row) => Boolean(row.has_downloads)).length,
      movies: rows.filter((row) => Boolean(row.has_movies)).length,
      radarr: rows.filter((row) => Boolean(row.has_radarr)).length,
      tv: rows.filter((row) => Boolean(row.has_tv)).length,
      sonarr: rows.filter((row) => Boolean(row.has_sonarr)).length,
      music: rows.filter((row) => Boolean(row.has_music)).length,
    };
  });

  readonly fileFilterCounts = computed<Record<FileFilter, number>>(() => {
    const rows = this.searchFilteredInventory().filter(
      (row) =>
        this.matchesCheckFilter(row, this.checkFilter()) &&
        this.matchesTrackerFilter(row, this.trackerFilter()) &&
        this.matchesLocationFilter(row, this.locationFilter()),
    );
    return {
      all: rows.length,
      video: rows.filter((row) => row.file_type === 'video').length,
      audio: rows.filter((row) => row.file_type === 'audio').length,
      other: rows.filter((row) => row.file_type === 'other').length,
    };
  });

  readonly trackerFilterCounts = computed<Record<string, number>>(() => {
    const rows = this.searchFilteredInventory().filter(
      (row) =>
        this.matchesCheckFilter(row, this.checkFilter()) &&
        this.matchesLocationFilter(row, this.locationFilter()) &&
        (this.fileFilter() === 'all' || row.file_type === this.fileFilter()),
    );
    const counts: Record<string, number> = { all: rows.length };
    for (const tracker of this.availableTrackers()) {
      counts[tracker] = rows.filter((row) => row.tracker_names.includes(tracker)).length;
    }
    return counts;
  });

  readonly activeFilterCount = computed(() => {
    let count = 0;
    if (this.filenameQuery().trim()) count += 1;
    if (this.checkFilter() !== 'all') count += 1;
    if (this.trackerFilter() !== 'all') count += 1;
    if (this.locationFilter() !== 'all') count += 1;
    if (this.fileFilter() !== 'all') count += 1;
    return count;
  });

  readonly hasActiveFilters = computed(() => this.activeFilterCount() > 0);

  initialize(destroyRef: DestroyRef): void {
    this.restoreFilterState();
    destroyRef.onDestroy(() => this.clearFilenameQueryDebounce());

    effect(() => {
      this.persistFilterState({
        q: this.filenameQuery(),
        check: this.checkFilter(),
        tracker: this.trackerFilter(),
        location: this.locationFilter(),
        type: this.fileFilter(),
        sort: this.sortKey(),
        direction: this.sortDirection(),
      });
    });
  }

  setInventory(rows: InventoryRow[]): void {
    this.inventory.set(rows);
  }

  setAvailableTrackers(trackers: string[]): void {
    this.availableTrackers.set(trackers);
    if (this.trackerFilter() !== 'all' && !trackers.includes(this.trackerFilter())) {
      this.trackerFilter.set('all');
    }
  }

  sortBy(key: SortKey): void {
    if (this.sortKey() === key) {
      this.sortDirection.set(this.sortDirection() === 'asc' ? 'desc' : 'asc');
      return;
    }
    this.sortKey.set(key);
    this.sortDirection.set(key === 'filenames_display' ? 'asc' : 'desc');
  }

  setCheckFilter(filter: CheckFilter): void {
    this.checkFilter.set(filter);
  }

  setFilenameQuery(value: string): void {
    this.filenameQuery.set(value);
    this.scheduleFilenameQueryApply(value);
  }

  clearFilenameQuery(): void {
    this.clearFilenameQueryDebounce();
    this.filenameQuery.set('');
    this.debouncedFilenameQuery.set('');
  }

  setLocationFilter(filter: LocationFilter): void {
    this.locationFilter.set(filter);
  }

  setTrackerFilter(filter: string): void {
    this.trackerFilter.set(filter);
  }

  setFileFilter(filter: FileFilter): void {
    this.fileFilter.set(filter);
  }

  resetFilters(): void {
    this.clearFilenameQuery();
    this.checkFilter.set('all');
    this.trackerFilter.set('all');
    this.locationFilter.set('all');
    this.fileFilter.set('all');
  }

  resetSort(): void {
    this.sortKey.set(DEFAULT_SORT_KEY);
    this.sortDirection.set(DEFAULT_SORT_DIRECTION);
  }

  hasCustomSort(): boolean {
    return this.sortKey() !== DEFAULT_SORT_KEY || this.sortDirection() !== DEFAULT_SORT_DIRECTION;
  }

  isSorted(key: SortKey): boolean {
    return this.sortKey() === key;
  }

  sortDirectionFor(key: SortKey): SortDirection | '' {
    return this.sortKey() === key ? this.sortDirection() : '';
  }

  isCheckFilterActive(filter: CheckFilter): boolean {
    return this.checkFilter() === filter;
  }

  checkFilterCount(filter: CheckFilter): number {
    return this.checkFilterCounts()[filter];
  }

  checkFilterLabel(filter: CheckFilter): string {
    return checkFilterLabel(filter);
  }

  isTrackerFilterActive(filter: string): boolean {
    return this.trackerFilter() === filter;
  }

  trackerFilterCount(filter: string): number {
    return this.trackerFilterCounts()[filter] ?? 0;
  }

  isLocationFilterActive(filter: LocationFilter): boolean {
    return this.locationFilter() === filter;
  }

  locationFilterLabel(filter: LocationFilter): string {
    return locationFilterLabel(filter);
  }

  locationFilterCount(filter: LocationFilter): number {
    return this.locationFilterCounts()[filter];
  }

  isFileFilterActive(filter: FileFilter): boolean {
    return this.fileFilter() === filter;
  }

  fileFilterLabel(filter: FileFilter): string {
    return fileFilterLabel(filter);
  }

  fileFilterCount(filter: FileFilter): number {
    return this.fileFilterCounts()[filter];
  }

  private filenameQueryTokens(): string[] {
    const query = this.normalizeSearchText(this.debouncedFilenameQuery());
    return query ? query.split(' ') : [];
  }

  private matchesFilenameQuery(row: InventoryRow, queryTokens: string[]): boolean {
    if (!queryTokens.length) {
      return true;
    }
    const normalizedFilename = this.normalizeSearchText(row.filenames_display);
    return queryTokens.every((token) => normalizedFilename.includes(token));
  }

  private matchesLocationFilter(row: InventoryRow, filter: LocationFilter): boolean {
    if (filter === 'all') return true;
    if (filter === 'downloads') return Boolean(row.has_downloads);
    if (filter === 'movies') return Boolean(row.has_movies);
    if (filter === 'radarr') return Boolean(row.has_radarr);
    if (filter === 'tv') return Boolean(row.has_tv);
    if (filter === 'sonarr') return Boolean(row.has_sonarr);
    return Boolean(row.has_music);
  }

  private matchesCheckFilter(row: InventoryRow, filter: CheckFilter): boolean {
    if (filter === 'all') return true;
    if (filter.startsWith('ko:')) {
      const ruleKey = filter.slice(3);
      return (row.check_results ?? []).some((check) => check.check_key === ruleKey && check.status === 'ko');
    }
    return row.consistency_status === filter;
  }

  private matchesTrackerFilter(row: InventoryRow, filter: string): boolean {
    if (filter === 'all') return true;
    return row.tracker_names.includes(filter);
  }

  private normalizeSearchText(value: string): string {
    return value.toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim().replace(/\s+/g, ' ');
  }

  private scheduleFilenameQueryApply(value: string): void {
    this.clearFilenameQueryDebounce();
    this.filenameQueryDebounceHandle = setTimeout(() => {
      this.debouncedFilenameQuery.set(value);
      this.filenameQueryDebounceHandle = null;
    }, FILENAME_FILTER_DEBOUNCE_MS);
  }

  private clearFilenameQueryDebounce(): void {
    if (this.filenameQueryDebounceHandle !== null) {
      clearTimeout(this.filenameQueryDebounceHandle);
      this.filenameQueryDebounceHandle = null;
    }
  }

  private restoreFilterState(): void {
    const state = this.readFilterStateFromUrl() ?? this.readFilterStateFromStorage();
    if (!state) {
      return;
    }
    this.filenameQuery.set(state.q);
    this.debouncedFilenameQuery.set(state.q);
    this.checkFilter.set(state.check);
    this.trackerFilter.set(state.tracker);
    this.locationFilter.set(state.location);
    this.fileFilter.set(state.type);
    this.sortKey.set(state.sort);
    this.sortDirection.set(state.direction);
  }

  private persistFilterState(state: PersistedFilterState): void {
    if (typeof window === 'undefined') {
      return;
    }

    const normalizedState: PersistedFilterState = {
      q: state.q.trim(),
      check: state.check,
      tracker: state.tracker,
      location: state.location,
      type: state.type,
      sort: state.sort,
      direction: state.direction,
    };

    const params = new URLSearchParams(window.location.search);
    this.setQueryParam(params, 'q', normalizedState.q);
    this.setQueryParam(params, 'check', normalizedState.check === 'all' ? '' : normalizedState.check);
    this.setQueryParam(params, 'tracker', normalizedState.tracker === 'all' ? '' : normalizedState.tracker);
    this.setQueryParam(params, 'location', normalizedState.location === 'all' ? '' : normalizedState.location);
    this.setQueryParam(params, 'type', normalizedState.type === 'all' ? '' : normalizedState.type);
    this.setQueryParam(params, 'sort', normalizedState.sort === DEFAULT_SORT_KEY ? '' : normalizedState.sort);
    this.setQueryParam(params, 'direction', normalizedState.direction === DEFAULT_SORT_DIRECTION ? '' : normalizedState.direction);

    const search = params.toString();
    const nextUrl = `${window.location.pathname}${search ? `?${search}` : ''}${window.location.hash}`;
    window.history.replaceState(window.history.state, '', nextUrl);
    window.localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(normalizedState));
  }

  private readFilterStateFromUrl(): PersistedFilterState | null {
    if (typeof window === 'undefined') {
      return null;
    }

    const params = new URLSearchParams(window.location.search);
    const q = params.get('q');
    const check = this.parseCheckFilter(params.get('check'));
    const tracker = params.get('tracker');
    const location = this.parseLocationFilter(params.get('location'));
    const type = this.parseFileFilter(params.get('type'));
    const sort = this.parseSortKey(params.get('sort'));
    const direction = this.parseSortDirection(params.get('direction'));

    if (q === null && check === null && tracker === null && location === null && type === null && sort === null && direction === null) {
      return null;
    }

    return {
      q: q ?? '',
      check: check ?? 'all',
      tracker: tracker ?? 'all',
      location: location ?? 'all',
      type: type ?? 'all',
      sort: sort ?? DEFAULT_SORT_KEY,
      direction: direction ?? DEFAULT_SORT_DIRECTION,
    };
  }

  private readFilterStateFromStorage(): PersistedFilterState | null {
    if (typeof window === 'undefined') {
      return null;
    }

    const raw = window.localStorage.getItem(FILTER_STORAGE_KEY);
    if (!raw) {
      return null;
    }

    try {
      const parsed = JSON.parse(raw) as Partial<PersistedFilterState>;
      return {
        q: typeof parsed.q === 'string' ? parsed.q : '',
        check: this.parseCheckFilter(parsed.check) ?? 'all',
        tracker: typeof parsed.tracker === 'string' && parsed.tracker.trim() ? parsed.tracker : 'all',
        location: this.parseLocationFilter(parsed.location) ?? 'all',
        type: this.parseFileFilter(parsed.type) ?? 'all',
        sort: this.parseSortKey(parsed.sort) ?? DEFAULT_SORT_KEY,
        direction: this.parseSortDirection(parsed.direction) ?? DEFAULT_SORT_DIRECTION,
      };
    } catch {
      return null;
    }
  }

  private parseCheckFilter(value: unknown): CheckFilter | null {
    if (typeof value !== 'string') return null;
    if (this.checkFilters.includes(value as CheckFilter)) return value as CheckFilter;
    if (value.startsWith('ko:') && CHECK_RULE_KEYS.some((rule) => rule.key === value.slice(3))) return value as CheckFilter;
    return null;
  }

  private parseLocationFilter(value: unknown): LocationFilter | null {
    return typeof value === 'string' && this.locationFilters.includes(value as LocationFilter) ? (value as LocationFilter) : null;
  }

  private parseFileFilter(value: unknown): FileFilter | null {
    return typeof value === 'string' && this.fileFilters.includes(value as FileFilter) ? (value as FileFilter) : null;
  }

  private parseSortKey(value: unknown): SortKey | null {
    return typeof value === 'string' && this.tableHeaders.some((header) => header.key === value) ? (value as SortKey) : null;
  }

  private parseSortDirection(value: unknown): SortDirection | null {
    return value === 'asc' || value === 'desc' ? value : null;
  }

  private setQueryParam(params: URLSearchParams, key: string, value: string): void {
    if (value) {
      params.set(key, value);
      return;
    }
    params.delete(key);
  }

  private compareValues(left: string | number, right: string | number): number {
    if (typeof left === 'number' && typeof right === 'number') {
      return left - right;
    }
    const leftNumber = Number(left);
    const rightNumber = Number(right);
    if (!Number.isNaN(leftNumber) && !Number.isNaN(rightNumber)) {
      return leftNumber - rightNumber;
    }
    return String(left).localeCompare(String(right), 'en', { numeric: true, sensitivity: 'base' });
  }
}
