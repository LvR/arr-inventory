import { ComponentFixture, fakeAsync, TestBed, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { App } from './app';
import { checkFilterLabel, jobHelpLines, torrentStatusClass, torrentStatusLabel, trackerStatusClass, trackerStatusLabel } from './core/utils/presentation.utils';

describe('App', () => {
  let httpMock: HttpTestingController;
  let fixture: ComponentFixture<App> | null;
  const baseUrl = window.location.pathname;
  const emptyDashboard = {
    settings: { app_name: 'ARR Inventory', data_root: '/data' },
    summary: { files: 0, downloads: 0, movies: 0, tv: 0, music: 0, torrents: 0, groups: 0, locations: 0, checks_ok: 0, checks_ko: 0 },
    jobs: [],
    inventory: [],
    meta: { last_inventory_at_display: 'never', total_duration_seconds: 0 },
    scan_job: null,
    filters: { trackers: [] },
  };
  const authenticatedSession = { authenticated: true, username: 'admin' };
  const anonymousSession = { authenticated: false };

  beforeEach(async () => {
    window.localStorage.clear();
    window.history.replaceState(window.history.state, '', baseUrl);

    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = null;
  });

  afterEach(() => {
    httpMock.match('/api/dashboard').forEach((request) => {
      if (!request.cancelled) {
        request.flush(emptyDashboard);
      }
    });
    httpMock.match('/api/auth/session').forEach((request) => request.flush(anonymousSession));
    fixture?.destroy();
    httpMock.verify();
    window.localStorage.clear();
    window.history.replaceState(window.history.state, '', baseUrl);
  });

  it('should create the app', () => {
    fixture = TestBed.createComponent(App);
    const session = httpMock.expectOne('/api/auth/session');
    session.flush(authenticatedSession);
    const request = httpMock.expectOne('/api/dashboard');
    request.flush({
      settings: { app_name: 'ARR Inventory', data_root: '/data' },
      summary: { files: 0, downloads: 0, movies: 0, tv: 0, music: 0, torrents: 0, groups: 0, locations: 0, checks_ok: 0, checks_ko: 0 },
      jobs: [
        { job_key: 'filesystem-scan', label: 'Filesystem scan', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'qbittorrent-sync', label: 'qBittorrent sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'radarr-sync', label: 'Radarr sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'sonarr-sync', label: 'Sonarr sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
      ],
      inventory: [],
      meta: { last_inventory_at_display: 'never', total_duration_seconds: 0 },
      scan_job: null,
      filters: { trackers: [] },
    });

    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('should render dashboard title after initial load', () => {
    fixture = TestBed.createComponent(App);
    const session = httpMock.expectOne('/api/auth/session');
    session.flush(authenticatedSession);
    const request = httpMock.expectOne('/api/dashboard');
    request.flush({
      settings: { app_name: 'ARR Inventory', data_root: '/data' },
      summary: { files: 5, downloads: 1, movies: 2, tv: 3, music: 0, torrents: 4, groups: 4, locations: 5, checks_ok: 3, checks_ko: 1 },
      jobs: [
        { job_key: 'filesystem-scan', label: 'Filesystem scan', state: 'done', progress: 100, message: '', duration_seconds: 2.5 },
        { job_key: 'qbittorrent-sync', label: 'qBittorrent sync', state: 'done', progress: 100, message: '', duration_seconds: 1.2 },
        { job_key: 'radarr-sync', label: 'Radarr sync', state: 'done', progress: 100, message: '', duration_seconds: 0.9 },
        { job_key: 'sonarr-sync', label: 'Sonarr sync', state: 'done', progress: 100, message: '', duration_seconds: 0.8 },
      ],
      inventory: [],
      meta: { last_inventory_at_display: 'now', total_duration_seconds: 3.7 },
      scan_job: null,
      filters: { trackers: [] },
    });

    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;

    expect(compiled.querySelector('h1')?.textContent).toContain('ARR Inventory');
    expect(compiled.textContent).toContain('Downloads');
    expect(compiled.textContent).toContain('Torrents');
    expect(compiled.textContent).toContain('Checks');
    expect(compiled.textContent).toContain('3');
    expect(compiled.textContent).toContain('1');
  });

  it('should filter inventory by filename query, location, and type', fakeAsync(() => {
    fixture = TestBed.createComponent(App);
    const session = httpMock.expectOne('/api/auth/session');
    session.flush(authenticatedSession);
    const request = httpMock.expectOne('/api/dashboard');
    request.flush({
      settings: { app_name: 'ARR Inventory', data_root: '/data' },
      summary: { files: 3, downloads: 1, movies: 1, tv: 1, music: 1, torrents: 1, groups: 3, locations: 4, checks_ok: 2, checks_ko: 1 },
      jobs: [
        { job_key: 'filesystem-scan', label: 'Filesystem scan', state: 'done', progress: 100, message: '', duration_seconds: 1 },
        { job_key: 'qbittorrent-sync', label: 'qBittorrent sync', state: 'done', progress: 100, message: '', duration_seconds: 1 },
        { job_key: 'radarr-sync', label: 'Radarr sync', state: 'done', progress: 100, message: '', duration_seconds: 1 },
        { job_key: 'sonarr-sync', label: 'Sonarr sync', state: 'done', progress: 100, message: '', duration_seconds: 1 },
      ],
      inventory: [
        {
          id: 1,
          consistency_status: 'pending',
          consistency_issue_count: 0,
          group_key: 'g1',
          device: 1,
          inode: 1,
          size_bytes: 100,
          size_bytes_display: '100 B',
          hardlink_count: 1,
          location_count: 1,
          filenames_display: 'Movie Alpha.mkv',
          has_downloads: 1,
          has_movies: 1,
          has_radarr: 1,
          has_tv: 0,
          has_sonarr: 0,
          has_music: 0,
          has_torrents: 1,
          torrent_count: 1,
          torrent_names: ['Movie Alpha Torrent'],
          torrents_tooltip: 'example',
          tracker_names: ['example'],
          check_results: [],
          file_type: 'video',
        },
        {
          id: 2,
          consistency_status: 'ko',
          consistency_issue_count: 2,
          group_key: 'g2',
          device: 1,
          inode: 2,
          size_bytes: 200,
          size_bytes_display: '200 B',
          hardlink_count: 1,
          location_count: 1,
          filenames_display: 'the.terror.S01E01.mkv',
          has_downloads: 0,
          has_movies: 0,
          has_radarr: 0,
          has_tv: 1,
          has_sonarr: 1,
          has_music: 0,
          has_torrents: 0,
          torrent_count: 0,
          torrent_names: [],
          torrents_tooltip: '',
          tracker_names: ['alpha'],
          check_results: [],
          file_type: 'video',
        },
        {
          id: 3,
          consistency_status: 'ok',
          consistency_issue_count: 0,
          group_key: 'g3',
          device: 1,
          inode: 3,
          size_bytes: 300,
          size_bytes_display: '300 B',
          hardlink_count: 1,
          location_count: 1,
          filenames_display: 'Song Gamma.flac',
          has_downloads: 0,
          has_movies: 0,
          has_radarr: 0,
          has_tv: 0,
          has_sonarr: 0,
          has_music: 1,
          has_torrents: 0,
          torrent_count: 0,
          torrent_names: [],
          torrents_tooltip: '',
          tracker_names: [],
          check_results: [],
          file_type: 'audio',
        },
      ],
      meta: { last_inventory_at_display: 'now', total_duration_seconds: 2 },
      scan_job: null,
      filters: { trackers: ['alpha', 'example'] },
    });

    fixture.detectChanges();
    const app = fixture.componentInstance as any;

    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual(['g3', 'g2', 'g1']);
    expect(app.filteredTotalSizeBytes()).toBe(600);
    expect(app.filteredTotalSizeDisplay()).toBe('600 B');

    app.setFilenameQuery('movie alpha');
    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual(['g3', 'g2', 'g1']);
    tick(200);
    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual(['g1']);
    expect(app.filteredTotalSizeBytes()).toBe(100);

    app.setFilenameQuery('The Terror');
    tick(200);
    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual(['g2']);
    expect(app.filteredTotalSizeBytes()).toBe(200);

    app.setFilenameQuery('song');
    tick(200);
    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual(['g3']);
    expect(app.filteredTotalSizeBytes()).toBe(300);

    app.setCheckFilter('ko');
    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual([]);
    expect(app.filteredTotalSizeBytes()).toBe(0);

    app.clearFilenameQuery();
    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual(['g2']);
    expect(app.filteredTotalSizeBytes()).toBe(200);
    app.setCheckFilter('all');
    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual(['g3', 'g2', 'g1']);
    expect(app.filteredTotalSizeBytes()).toBe(600);
    app.setLocationFilter('tv');
    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual(['g2']);
    expect(app.filteredTotalSizeBytes()).toBe(200);
    app.setTrackerFilter('alpha');
    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual(['g2']);
    expect(app.filteredTotalSizeBytes()).toBe(200);
    app.setTrackerFilter('example');
    expect(app.sortedInventory()).toEqual([]);
    expect(app.filteredTotalSizeBytes()).toBe(0);

    app.setLocationFilter('all');
    app.setTrackerFilter('all');
    app.setLocationFilter('radarr');
    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual(['g1']);
    expect(app.filteredTotalSizeBytes()).toBe(100);
    app.setLocationFilter('sonarr');
    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual(['g2']);
    expect(app.filteredTotalSizeBytes()).toBe(200);
    app.setLocationFilter('all');
    app.setFileFilter('audio');
    expect(app.sortedInventory().map((row: { group_key: string }) => row.group_key)).toEqual(['g3']);
    expect(app.filteredTotalSizeBytes()).toBe(300);
  }));

  it('should restore filters from url and persist them to storage', fakeAsync(() => {
    window.history.replaceState(window.history.state, '', `${baseUrl}?q=the%20terror&check=ko&location=tv&type=video&sort=filenames_display&direction=asc`);

    fixture = TestBed.createComponent(App);
    const session = httpMock.expectOne('/api/auth/session');
    session.flush(authenticatedSession);
    const request = httpMock.expectOne('/api/dashboard');
    request.flush({
      settings: { app_name: 'ARR Inventory', data_root: '/data' },
      summary: { files: 0, downloads: 0, movies: 0, tv: 0, music: 0, torrents: 0, groups: 0, locations: 0, checks_ok: 0, checks_ko: 0 },
      jobs: [
        { job_key: 'filesystem-scan', label: 'Filesystem scan', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'qbittorrent-sync', label: 'qBittorrent sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'radarr-sync', label: 'Radarr sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'sonarr-sync', label: 'Sonarr sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
      ],
      inventory: [],
      meta: { last_inventory_at_display: 'never', total_duration_seconds: 0 },
      scan_job: null,
    });

    fixture.detectChanges();
    const app = fixture.componentInstance as any;

    expect(app.filenameQuery()).toBe('the terror');
    expect(app.checkFilter()).toBe('ko');
    expect(app.trackerFilter()).toBe('all');
    expect(app.locationFilter()).toBe('tv');
    expect(app.fileFilter()).toBe('video');
    expect(app.sortKey()).toBe('filenames_display');
    expect(app.sortDirection()).toBe('asc');

    app.setFilenameQuery('new query');
    app.setCheckFilter('ok');
    app.setLocationFilter('music');
    app.setFileFilter('audio');
    app.sortBy('size_bytes');
    tick(200);
    fixture.detectChanges();

    expect(window.location.search).toContain('q=new+query');
    expect(window.location.search).toContain('check=ok');
    expect(window.location.search).toContain('location=music');
    expect(window.location.search).toContain('type=audio');
    expect(window.location.search).toContain('sort=size_bytes');
    expect(window.location.search).not.toContain('direction=');
    expect(JSON.parse(window.localStorage.getItem('arr-inventory.filters') || '{}')).toEqual({
      q: 'new query',
      check: 'ok',
      tracker: 'all',
      location: 'music',
      type: 'audio',
      sort: 'size_bytes',
      direction: 'desc',
    });
  }));

  it('should reset all filters without resetting sort', fakeAsync(() => {
    fixture = TestBed.createComponent(App);
    const session = httpMock.expectOne('/api/auth/session');
    session.flush(authenticatedSession);
    const request = httpMock.expectOne('/api/dashboard');
    request.flush({
      settings: { app_name: 'ARR Inventory', data_root: '/data' },
      summary: { files: 0, downloads: 0, movies: 0, tv: 0, music: 0, torrents: 0, groups: 0, locations: 0, checks_ok: 0, checks_ko: 0 },
      jobs: [
        { job_key: 'filesystem-scan', label: 'Filesystem scan', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'qbittorrent-sync', label: 'qBittorrent sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'radarr-sync', label: 'Radarr sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'sonarr-sync', label: 'Sonarr sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
      ],
      inventory: [],
      meta: { last_inventory_at_display: 'never', total_duration_seconds: 0 },
      scan_job: null,
    });

    fixture.detectChanges();
    const app = fixture.componentInstance as any;

    app.setFilenameQuery('abc');
    app.setCheckFilter('ko');
    app.setTrackerFilter('example');
    app.setLocationFilter('movies');
    app.setFileFilter('video');
    app.sortBy('filenames_display');
    tick(200);
    fixture.detectChanges();

    app.resetFilters();
    fixture.detectChanges();

    expect(app.filenameQuery()).toBe('');
    expect(app.debouncedFilenameQuery()).toBe('');
    expect(app.checkFilter()).toBe('all');
    expect(app.trackerFilter()).toBe('all');
    expect(app.locationFilter()).toBe('all');
    expect(app.fileFilter()).toBe('all');
    expect(app.sortKey()).toBe('filenames_display');
    expect(window.location.search).toContain('sort=filenames_display');
    expect(window.location.search).not.toContain('q=');
    expect(window.location.search).not.toContain('check=');
    expect(window.location.search).not.toContain('location=');
    expect(window.location.search).not.toContain('type=');
    expect(window.location.search).toContain('direction=asc');
  }));

  it('should reset sort independently from filters', fakeAsync(() => {
    fixture = TestBed.createComponent(App);
    const session = httpMock.expectOne('/api/auth/session');
    session.flush(authenticatedSession);
    const request = httpMock.expectOne('/api/dashboard');
    request.flush({
      settings: { app_name: 'ARR Inventory', data_root: '/data' },
      summary: { files: 0, downloads: 0, movies: 0, tv: 0, music: 0, torrents: 0, groups: 0, locations: 0, checks_ok: 0, checks_ko: 0 },
      jobs: [
        { job_key: 'filesystem-scan', label: 'Filesystem scan', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'qbittorrent-sync', label: 'qBittorrent sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'radarr-sync', label: 'Radarr sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'sonarr-sync', label: 'Sonarr sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
      ],
      inventory: [],
      meta: { last_inventory_at_display: 'never', total_duration_seconds: 0 },
      scan_job: null,
    });

    fixture.detectChanges();
    const app = fixture.componentInstance as any;

    app.setFilenameQuery('abc');
    app.setCheckFilter('ko');
    app.setTrackerFilter('example');
    app.setLocationFilter('tv');
    app.sortBy('filenames_display');
    app.sortBy('filenames_display');
    tick(200);
    fixture.detectChanges();

    expect(app.hasCustomSort()).toBeTrue();
    expect(app.hasActiveFilters()).toBeTrue();
    expect(app.activeFilterCount()).toBe(4);

    app.resetSort();
    fixture.detectChanges();

    expect(app.sortKey()).toBe('group_key');
    expect(app.sortDirection()).toBe('desc');
    expect(app.filenameQuery()).toBe('abc');
    expect(app.checkFilter()).toBe('ko');
    expect(app.trackerFilter()).toBe('example');
    expect(app.locationFilter()).toBe('tv');
    expect(app.hasCustomSort()).toBeFalse();
    expect(window.location.search).not.toContain('sort=');
    expect(window.location.search).not.toContain('direction=');
    expect(window.location.search).toContain('q=abc');
    expect(window.location.search).toContain('check=ko');
    expect(window.location.search).toContain('tracker=example');
    expect(window.location.search).toContain('location=tv');
  }));

  it('should purge before starting a new analysis and keep stop available during launch', fakeAsync(() => {
    fixture = TestBed.createComponent(App);
    const session = httpMock.expectOne('/api/auth/session');
    session.flush(authenticatedSession);
    const initialRequest = httpMock.expectOne('/api/dashboard');
    initialRequest.flush({
      settings: { app_name: 'ARR Inventory', data_root: '/data' },
      summary: { files: 2, downloads: 1, movies: 1, tv: 0, music: 0, torrents: 1, groups: 1, locations: 2, checks_ok: 1, checks_ko: 0 },
      jobs: [
        { job_key: 'filesystem-scan', label: 'Filesystem scan', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'qbittorrent-sync', label: 'qBittorrent sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'radarr-sync', label: 'Radarr sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
        { job_key: 'sonarr-sync', label: 'Sonarr sync', state: 'idle', progress: 0, message: '', duration_seconds: 0 },
      ],
      inventory: [
        {
          id: 1,
          consistency_status: 'ok',
          consistency_issue_count: 0,
          group_key: 'g1',
          device: 1,
          inode: 1,
          size_bytes: 100,
          size_bytes_display: '100 B',
          hardlink_count: 1,
          location_count: 1,
          filenames_display: 'Movie Alpha.mkv',
          has_downloads: 1,
          has_movies: 1,
          has_radarr: 1,
          has_tv: 0,
          has_sonarr: 0,
          has_music: 0,
          has_torrents: 1,
          torrent_count: 1,
          torrent_names: [],
          torrents_tooltip: '',
          tracker_names: [],
          check_results: [],
          file_type: 'video',
        },
      ],
      meta: { last_inventory_at_display: 'now', total_duration_seconds: 2 },
      scan_job: null,
    });

    fixture.detectChanges();
    const app = fixture.componentInstance as any;

    app.startScan();
    fixture.detectChanges();

    expect(app.analysisInProgress()).toBeTrue();
    expect(app.sortedInventory().length).toBe(0);

    const compiled = fixture.nativeElement as HTMLElement;
    const primaryButton = compiled.querySelector('.hero__action-row .icon-button--stop') as HTMLButtonElement;
    expect(primaryButton.getAttribute('aria-label')).toBe('Stop analyse');
    expect(primaryButton.disabled).toBeFalse();

    const purgeRequest = httpMock.expectOne('/api/inventory/purge');
    purgeRequest.flush({ status: 'purged' });

    const startRequest = httpMock.expectOne('/api/scan/filesystem');
    startRequest.flush({ status: 'started' });

    const refreshRequest = httpMock.expectOne('/api/dashboard');
    refreshRequest.flush({
      settings: { app_name: 'ARR Inventory', data_root: '/data' },
      summary: { files: 0, downloads: 0, movies: 0, tv: 0, music: 0, torrents: 0, groups: 0, locations: 0, checks_ok: 0, checks_ko: 0 },
      jobs: [
        { job_key: 'filesystem-scan', label: 'Filesystem scan', state: 'running', progress: 1, message: 'Scan starting...', duration_seconds: 0.2 },
        { job_key: 'qbittorrent-sync', label: 'qBittorrent sync', state: 'queued', progress: 0, message: 'Waiting for filesystem scan', duration_seconds: 0 },
        { job_key: 'radarr-sync', label: 'Radarr sync', state: 'queued', progress: 0, message: 'Waiting for qBittorrent sync', duration_seconds: 0 },
        { job_key: 'sonarr-sync', label: 'Sonarr sync', state: 'queued', progress: 0, message: 'Waiting for Radarr sync', duration_seconds: 0 },
      ],
      inventory: [],
      meta: { last_inventory_at_display: 'never', total_duration_seconds: 0.2 },
      scan_job: { job_key: 'filesystem-scan', label: 'Filesystem scan', state: 'running', progress: 1, message: 'Scan starting...', duration_seconds: 0.2 },
    });

    tick();
    expect(app.isScanning()).toBeTrue();
  }));

  it('should stop a launch before the scan request is sent', fakeAsync(() => {
    fixture = TestBed.createComponent(App);
    const session = httpMock.expectOne('/api/auth/session');
    session.flush(authenticatedSession);
    const initialRequest = httpMock.expectOne('/api/dashboard');
    initialRequest.flush({
      settings: { app_name: 'ARR Inventory', data_root: '/data' },
      summary: { files: 1, downloads: 1, movies: 0, tv: 0, music: 0, torrents: 0, groups: 1, locations: 1, checks_ok: 0, checks_ko: 0 },
      jobs: [],
      inventory: [
        {
          id: 1,
          consistency_status: 'pending',
          consistency_issue_count: 0,
          group_key: 'g1',
          device: 1,
          inode: 1,
          size_bytes: 100,
          size_bytes_display: '100 B',
          hardlink_count: 1,
          location_count: 1,
          filenames_display: 'Movie Alpha.mkv',
          has_downloads: 1,
          has_movies: 0,
          has_radarr: 0,
          has_tv: 0,
          has_sonarr: 0,
          has_music: 0,
          has_torrents: 0,
          torrent_count: 0,
          torrent_names: [],
          torrents_tooltip: '',
          tracker_names: [],
          check_results: [],
          file_type: 'video',
        },
      ],
      meta: { last_inventory_at_display: 'now', total_duration_seconds: 1 },
      scan_job: null,
    });

    fixture.detectChanges();
    const app = fixture.componentInstance as any;

    app.startScan();
    const purgeRequest = httpMock.expectOne('/api/inventory/purge');

    app.stopScan();
    expect(app.isStopping()).toBeTrue();

    purgeRequest.flush({ status: 'purged' });
    tick();
    fixture.detectChanges();

    httpMock.expectNone('/api/scan/filesystem');
    expect(app.analysisInProgress()).toBeFalse();
    expect(app.isStopping()).toBeFalse();
  }));

  it('should map torrent statuses to friendly labels and badge classes', () => {
    expect(torrentStatusLabel('uploading')).toBe('Seeding');
    expect(torrentStatusLabel('stalledUP')).toBe('Seeding stalled');
    expect(torrentStatusLabel('pausedDL')).toBe('Paused download');
    expect(torrentStatusLabel('missingFiles')).toBe('Missing files');
    expect(torrentStatusLabel('checkingResumeData')).toBe('Checking resume data');
    expect(torrentStatusLabel('forcedMetaDL')).toBe('Forced metadata download');
    expect(torrentStatusClass('uploading')).toBe('state-badge state-badge--done');
    expect(torrentStatusClass('missingFiles')).toBe('state-badge state-badge--error');
    expect(torrentStatusClass('pausedDL')).toBe('state-badge state-badge--idle');
    expect(torrentStatusClass('forcedUP')).toBe('state-badge state-badge--done');
    expect(torrentStatusClass('checkingDL')).toBe('state-badge state-badge--running');
  });

  it('should map tracker statuses to friendly labels and badge classes', () => {
    expect(trackerStatusLabel('0')).toBe('Disabled');
    expect(trackerStatusLabel('1')).toBe('Not contacted');
    expect(trackerStatusLabel('2')).toBe('Working');
    expect(trackerStatusLabel('3')).toBe('Updating');
    expect(trackerStatusLabel('4')).toBe('Not working');
    expect(trackerStatusLabel('5')).toBe('Tracker error');
    expect(trackerStatusLabel('6')).toBe('Unreachable');
    expect(trackerStatusLabel('working')).toBe('Working');
    expect(trackerStatusLabel('Updating...')).toBe('Updating');
    expect(trackerStatusLabel('Not contacted yet')).toBe('Not contacted');
    expect(trackerStatusClass('2')).toBe('state-badge state-badge--done');
    expect(trackerStatusClass('3')).toBe('state-badge state-badge--running');
    expect(trackerStatusClass('4')).toBe('state-badge state-badge--error');
    expect(trackerStatusClass('0')).toBe('state-badge state-badge--idle');
  });

  it('should render login screen when session is anonymous', () => {
    fixture = TestBed.createComponent(App);
    const session = httpMock.expectOne('/api/auth/session');
    session.flush(anonymousSession);

    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;

    expect(compiled.textContent).toContain('Admin access');
    expect(compiled.textContent).toContain('Sign in');
  });

  it('should login and load dashboard', fakeAsync(() => {
    fixture = TestBed.createComponent(App);
    const session = httpMock.expectOne('/api/auth/session');
    session.flush(anonymousSession);

    fixture.detectChanges();
    const app = fixture.componentInstance as any;
    app.setLoginUsername('admin');
    app.setLoginPassword('secret');
    app.login();

    const loginRequest = httpMock.expectOne('/api/auth/login');
    expect(loginRequest.request.body).toEqual({ username: 'admin', password: 'secret' });
    loginRequest.flush(authenticatedSession);

    const dashboardRequest = httpMock.expectOne('/api/dashboard');
    dashboardRequest.flush(emptyDashboard);
    tick();
    fixture.detectChanges();

    expect(app.isAuthenticated()).toBeTrue();
    expect(app.authUsername()).toBe('admin');
  }));

  it('should show backend throttle message on rate limit', fakeAsync(() => {
    fixture = TestBed.createComponent(App);
    const session = httpMock.expectOne('/api/auth/session');
    session.flush(anonymousSession);

    fixture.detectChanges();
    const app = fixture.componentInstance as any;
    app.setLoginUsername('admin');
    app.setLoginPassword('wrong');
    app.login();

    const loginRequest = httpMock.expectOne('/api/auth/login');
    loginRequest.flush({ detail: 'Too many login attempts. Try again in 4s.' }, { status: 429, statusText: 'Too Many Requests' });
    tick();

    expect(app.authError()).toContain('Try again in 4s');
    expect(app.isAuthenticated()).toBeFalse();
  }));

  it('should show Radarr job help text', () => {
    expect(jobHelpLines('radarr-sync')).toEqual(['Loads Radarr movies and queue items, then matches them to indexed files.']);
  });

  it('should show Sonarr job help text', () => {
    expect(jobHelpLines('sonarr-sync')).toEqual(['Loads Sonarr episode files and queue items, then matches them to indexed files.']);
  });

  it('should expose new consistency rule labels', () => {
    expect(checkFilterLabel('ko:movies_radarr_consistent')).toBe('Movies match Radarr');
    expect(checkFilterLabel('ko:tv_sonarr_consistent')).toBe('TV match Sonarr');
    expect(checkFilterLabel('ko:download_torrent_still_useful')).toBe('Download torrent still useful');
    expect(jobHelpLines('consistency-check')).toContain('Movies match Radarr: movies files and imported Radarr entries must match each other.');
    expect(jobHelpLines('consistency-check')).toContain('TV match Sonarr: TV files and imported Sonarr entries must match each other.');
    expect(jobHelpLines('consistency-check')).toContain('Download torrent still useful: downloads-only groups become KO only when all matched torrents exceed the configured seed time and ratio thresholds.');
  });
});
