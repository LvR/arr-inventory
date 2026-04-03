import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { catchError, finalize, interval, of, startWith, switchMap } from 'rxjs';
import { CHECK_RULE_KEYS } from './core/constants/inventory.constants';
import { TORRENT_STATUS_CLASSES, TORRENT_STATUS_LABELS, TRACKER_STATUS_CLASSES, TRACKER_STATUS_LABELS } from './core/constants/status.constants';
import { anonymousSessionState, SessionResponse } from './core/models/auth.models';
import { CheckFilter, CheckStatus, DashboardResponse, FileFilter, GroupDetail, InventoryRow, JobState, LocationFilter, Meta, SortDirection, SortKey, Summary, UiTooltip } from './core/models/dashboard.models';
import { AuthService } from './core/services/auth.service';
import { DashboardService } from './core/services/dashboard.service';
import { InventoryStateService } from './core/services/inventory-state.service';
import {
  checkFilterLabel,
  fileFilterLabel,
  jobHelpLines,
  statusLabel,
  totalDuration,
} from './core/utils/presentation.utils';
import { AuthLoginCardComponent } from './features/auth/auth-login-card.component';
import { DashboardHeaderComponent } from './features/dashboard/components/dashboard-header.component';
import { JobsPanelComponent } from './features/dashboard/components/jobs-panel.component';
import { GroupDetailModalComponent } from './features/inventory/components/group-detail-modal.component';
import { InventoryFiltersComponent } from './features/inventory/components/inventory-filters.component';
import { InventoryTableComponent } from './features/inventory/components/inventory-table.component';
import { UiTooltipComponent } from './shared/components/ui-tooltip.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, AuthLoginCardComponent, DashboardHeaderComponent, JobsPanelComponent, GroupDetailModalComponent, InventoryFiltersComponent, InventoryTableComponent, UiTooltipComponent],
  templateUrl: './app.html',
  styleUrl: './app.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class App {
  private readonly authService = inject(AuthService);
  private readonly dashboardService = inject(DashboardService);
  private readonly inventoryState = inject(InventoryStateService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly appName = 'ARR Inventory';
  protected readonly dataRoot = signal('/data');
  protected readonly sessionChecked = signal(false);
  protected readonly isAuthenticated = signal(false);
  protected readonly authUsername = signal('');
  protected readonly loginUsername = signal('');
  protected readonly loginPassword = signal('');
  protected readonly isLoggingIn = signal(false);
  protected readonly authError = signal('');
  protected readonly tooltip = signal<UiTooltip | null>(null);
  protected readonly summary = signal<Summary>({
    files: 0,
    downloads: 0,
    movies: 0,
    tv: 0,
    music: 0,
    torrents: 0,
    groups: 0,
    locations: 0,
    checks_ok: 0,
    checks_ko: 0,
  });
  protected readonly jobs = signal<JobState[]>([]);
  protected readonly inventory = this.inventoryState.inventory;
  protected readonly meta = signal<Meta>({ last_inventory_at_display: 'never' });
  protected readonly scanJob = signal<JobState | null>(null);
  protected readonly selectedGroupDetail = signal<GroupDetail | null>(null);
  protected readonly isScanning = signal(false);
  protected readonly isLaunchingScan = signal(false);
  protected readonly isPurging = signal(false);
  protected readonly isLoadingDetail = signal(false);
  protected readonly isStopping = signal(false);
  protected readonly errorMessage = signal('');
  protected readonly sortKey = this.inventoryState.sortKey;
  protected readonly sortDirection = this.inventoryState.sortDirection;
  protected readonly filenameQuery = this.inventoryState.filenameQuery;
  protected readonly debouncedFilenameQuery = this.inventoryState.debouncedFilenameQuery;
  protected readonly checkFilter = this.inventoryState.checkFilter;
  protected readonly trackerFilter = this.inventoryState.trackerFilter;
  protected readonly locationFilter = this.inventoryState.locationFilter;
  protected readonly fileFilter = this.inventoryState.fileFilter;
  protected readonly availableTrackers = this.inventoryState.availableTrackers;
  protected readonly tableHeaders = this.inventoryState.tableHeaders;
  protected readonly totalJobs = 5;
  protected readonly checkGlobalFilters = this.inventoryState.checkGlobalFilters;
  protected readonly checkRuleFilters = this.inventoryState.checkRuleFilters;
  protected readonly locationFilters = this.inventoryState.locationFilters;
  protected readonly fileFilters = this.inventoryState.fileFilters;
  private cancelScanLaunchRequested = false;
  protected readonly sortedInventory = this.inventoryState.sortedInventory;

  protected readonly filteredTotalSizeBytes = this.inventoryState.filteredTotalSizeBytes;
  protected readonly filteredTotalSizeDisplay = this.inventoryState.filteredTotalSizeDisplay;
  protected readonly checkFilterCounts = this.inventoryState.checkFilterCounts;
  protected readonly locationFilterCounts = this.inventoryState.locationFilterCounts;
  protected readonly fileFilterCounts = this.inventoryState.fileFilterCounts;
  protected readonly trackerFilterCounts = this.inventoryState.trackerFilterCounts;
  protected readonly activeFilterCount = this.inventoryState.activeFilterCount;
  protected readonly hasActiveFilters = this.inventoryState.hasActiveFilters;

  constructor() {
    this.inventoryState.initialize(this.destroyRef);

    this.initializeSession();

    interval(2000)
      .pipe(
        startWith(0),
        switchMap(() => (this.isAuthenticated() ? this.fetchDashboardSnapshot() : of(null))),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((dashboard) => {
        if (dashboard) {
          this.applyDashboard(dashboard);
        }
      });
  }

  protected setLoginUsername(value: string): void {
    this.loginUsername.set(value);
  }

  protected setLoginPassword(value: string): void {
    this.loginPassword.set(value);
  }

  protected login(): void {
    if (this.isLoggingIn()) {
      return;
    }
    if (!this.loginUsername().trim() || !this.loginPassword()) {
      this.authError.set('Enter username and password.');
      this.sessionChecked.set(true);
      return;
    }
    this.isLoggingIn.set(true);
    this.authError.set('');
    this.authService
      .login(this.loginUsername().trim(), this.loginPassword())
      .pipe(
        switchMap((session) => {
          this.applySession(session);
          return this.fetchDashboardSnapshot();
        }),
        catchError((error: unknown) => {
          if (this.isUnauthorizedError(error)) {
            this.authError.set('Invalid username or password.');
            this.setUnauthenticatedState();
            return of(null);
          }
          if (error instanceof HttpErrorResponse && error.status === 429) {
            this.authError.set(typeof error.error?.detail === 'string' ? error.error.detail : 'Too many login attempts.');
            return of(null);
          }
          this.authError.set('Unable to sign in.');
          return of(null);
        }),
        finalize(() => {
          this.isLoggingIn.set(false);
          this.sessionChecked.set(true);
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((dashboard) => {
        if (dashboard) {
          this.applyDashboard(dashboard);
        }
      });
  }

  protected logout(): void {
    this.authService
      .logout()
      .pipe(
        catchError(() => of(anonymousSessionState())),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe(() => this.setUnauthenticatedState());
  }

  protected sortBy(key: SortKey): void {
    this.inventoryState.sortBy(key);
  }

  protected showCheckTooltip(event: MouseEvent, lines: string[]): void {
    this.showTooltip(event, 'Check rules', lines);
  }

  protected showTrackerTooltip(event: MouseEvent, lines: string[]): void {
    this.showTooltip(event, 'Trackers', lines);
  }

  protected showJobHelpTooltip(event: MouseEvent, title: string, lines: string[]): void {
    this.showTooltip(event, title, lines);
  }

  protected startScan(): void {
    if (this.isScanning() || this.isPurging() || this.isLaunchingScan()) {
      return;
    }
    this.errorMessage.set('');
    this.cancelScanLaunchRequested = false;
    this.isLaunchingScan.set(true);
    this.isScanning.set(true);
    this.isStopping.set(false);
    this.isPurging.set(true);
    this.selectedGroupDetail.set(null);
    this.applyDashboard({
      settings: { app_name: this.appName, data_root: this.dataRoot() },
      summary: {
        files: 0,
        downloads: 0,
        movies: 0,
        tv: 0,
        music: 0,
        torrents: 0,
        groups: 0,
        locations: 0,
        checks_ok: 0,
        checks_ko: 0,
      },
      jobs: [],
      inventory: [],
      meta: { last_inventory_at_display: 'never', total_duration_seconds: 0 },
      scan_job: null,
    });
    this.dashboardService
      .purgeInventory()
      .pipe(
        switchMap(() => (this.cancelScanLaunchRequested ? of(false) : this.dashboardService.startScan().pipe(switchMap(() => of(true))))),
        switchMap((started) => (started ? this.fetchDashboardSnapshot() : of(null))),
        catchError(() => {
          this.errorMessage.set('Unable to start analysis.');
          return of(null);
        }),
        finalize(() => {
          this.isPurging.set(false);
          this.isLaunchingScan.set(false);
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((dashboard) => {
        if (dashboard) {
          this.applyDashboard(dashboard);
          return;
        }
        this.applyDashboard({
          settings: { app_name: this.appName, data_root: this.dataRoot() },
          summary: {
            files: 0,
            downloads: 0,
            movies: 0,
            tv: 0,
            music: 0,
            torrents: 0,
            groups: 0,
            locations: 0,
            checks_ok: 0,
            checks_ko: 0,
          },
          jobs: [],
          inventory: [],
          meta: { last_inventory_at_display: 'never', total_duration_seconds: 0 },
          scan_job: null,
        });
      });
  }

  protected stopScan(): void {
    if ((!this.isScanning() && !this.isLaunchingScan()) || this.isStopping()) {
      return;
    }
    if (this.isLaunchingScan() && this.isPurging()) {
      this.cancelScanLaunchRequested = true;
      this.isScanning.set(false);
      this.isStopping.set(true);
      return;
    }
    this.isStopping.set(true);
    this.errorMessage.set('');
    this.dashboardService
      .stopScan()
      .pipe(
        switchMap(() => this.fetchDashboardSnapshot()),
        catchError(() => {
          this.errorMessage.set('Unable to stop analysis.');
          return of(null);
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((dashboard) => {
        if (dashboard) {
          this.applyDashboard(dashboard);
        }
        this.isStopping.set(this.isScanning());
      });
  }

  protected purgeInventory(): void {
    if (this.isScanning() || this.isPurging()) {
      return;
    }
    this.isPurging.set(true);
    this.errorMessage.set('');
    this.dashboardService
      .purgeInventory()
      .pipe(
        switchMap(() => this.fetchDashboardSnapshot()),
        catchError(() => {
          this.errorMessage.set('Unable to purge inventory.');
          return of(null);
        }),
        finalize(() => this.isPurging.set(false)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((dashboard) => {
        if (dashboard) {
          this.applyDashboard(dashboard);
        }
      });
  }

  protected openGroupDetail(groupId: number): void {
    this.dashboardService
      .fetchGroupDetail(groupId)
      .pipe(
        catchError(() => {
          this.errorMessage.set('Unable to load group details.');
          return of(null);
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((detail) => {
        if (detail) {
          this.selectedGroupDetail.set({
            ...detail,
            torrents: detail.torrents.map((torrent) => ({
              ...torrent,
              tracker_names: torrent.tracker_names ?? [],
              trackers: torrent.trackers ?? [],
              files: torrent.files ?? [],
            })),
            radarr: {
              imported: detail.radarr?.imported ?? [],
              queue: detail.radarr?.queue ?? [],
            },
            sonarr: {
              imported: detail.sonarr?.imported ?? [],
              queue: detail.sonarr?.queue ?? [],
            },
          });
        }
      });
  }

  protected closeGroupDetail(): void {
    this.selectedGroupDetail.set(null);
  }

  protected copyPath(path: string, event: MouseEvent): void {
    event.stopPropagation();
    navigator.clipboard.writeText(path);
  }

  protected completedJobsCount(): number {
    return this.jobs().filter((job) => job.state === 'done' || job.state === 'idle').length;
  }

  protected setCheckFilter(filter: CheckFilter): void {
    this.inventoryState.setCheckFilter(filter);
  }

  protected setFilenameQuery(value: string): void {
    this.inventoryState.setFilenameQuery(value);
  }

  protected clearFilenameQuery(): void {
    this.inventoryState.clearFilenameQuery();
  }

  protected setLocationFilter(filter: LocationFilter): void {
    this.inventoryState.setLocationFilter(filter);
  }

  protected setTrackerFilter(filter: string): void {
    this.inventoryState.setTrackerFilter(filter);
  }

  protected setFileFilter(filter: FileFilter): void {
    this.inventoryState.setFileFilter(filter);
  }

  protected resetFilters(): void {
    this.inventoryState.resetFilters();
  }

  protected resetSort(): void {
    this.inventoryState.resetSort();
  }

  protected hasCustomSort(): boolean {
    return this.inventoryState.hasCustomSort();
  }

  protected showTooltip(event: MouseEvent, title: string, lines: string[]): void {
    this.tooltip.set({ title, lines, x: -9999, y: -9999 });
    requestAnimationFrame(() => {
      if (!this.tooltip()) return;
      const el = document.querySelector('.ui-tooltip') as HTMLElement | null;
      const rect = el?.getBoundingClientRect();
      const w = rect?.width ?? 100;
      const h = rect?.height ?? 40;
      this.tooltip.set(this.positionTooltip(title, lines, event.clientX, event.clientY, w, h));
    });
  }

  protected moveTooltip(event: MouseEvent): void {
    const current = this.tooltip();
    if (!current) {
      return;
    }
    const el = document.querySelector('.ui-tooltip') as HTMLElement | null;
    const rect = el?.getBoundingClientRect();
    const w = rect?.width ?? 100;
    const h = rect?.height ?? 40;
    this.tooltip.set(this.positionTooltip(current.title, current.lines, event.clientX, event.clientY, w, h));
  }

  protected hideTooltip(): void {
    this.tooltip.set(null);
  }

  protected analysisInProgress(): boolean {
    return this.isScanning() || this.isLaunchingScan();
  }

  protected totalDuration(): string {
    return totalDuration(this.meta().total_duration_seconds ?? 0);
  }

  private fetchDashboardSnapshot() {
    return this.dashboardService.fetchDashboardSnapshot().pipe(
      catchError((error: unknown) => {
        if (this.isUnauthorizedError(error)) {
          this.setUnauthenticatedState();
          return of(null);
        }
        this.errorMessage.set('Unable to refresh dashboard data.');
        return of({
          settings: { app_name: this.appName, data_root: this.dataRoot() },
          summary: this.summary(),
          jobs: this.jobs(),
          inventory: this.inventory(),
          meta: this.meta(),
          scan_job: this.scanJob(),
        });
      }),
    );
  }

  private initializeSession(): void {
    this.authService
      .session()
      .pipe(
        switchMap((session) => {
          this.applySession(session);
          return session.authenticated ? this.fetchDashboardSnapshot() : of(null);
        }),
        catchError(() => {
          this.setUnauthenticatedState();
          return of(null);
        }),
        finalize(() => this.sessionChecked.set(true)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((dashboard) => {
        if (dashboard) {
          this.applyDashboard(dashboard);
        }
      });
  }

  private applySession(session: SessionResponse): void {
    if (!session.authenticated) {
      this.setUnauthenticatedState();
      return;
    }
    this.isAuthenticated.set(true);
    this.authUsername.set(session.username || 'admin');
    this.authError.set('');
  }

  private setUnauthenticatedState(): void {
    this.isAuthenticated.set(false);
    this.authUsername.set('');
    this.inventoryState.setAvailableTrackers([]);
    this.isScanning.set(false);
    this.isLaunchingScan.set(false);
    this.isPurging.set(false);
    this.isStopping.set(false);
    this.selectedGroupDetail.set(null);
    this.hideTooltip();
    this.errorMessage.set('');
    this.applyDashboard(this.emptyDashboardState());
  }

  private emptyDashboardState(): DashboardResponse {
    return {
      settings: { app_name: this.appName, data_root: this.dataRoot() },
      summary: {
        files: 0,
        downloads: 0,
        movies: 0,
        tv: 0,
        music: 0,
        torrents: 0,
        groups: 0,
        locations: 0,
        checks_ok: 0,
        checks_ko: 0,
      },
      jobs: [],
      inventory: [],
      meta: { last_inventory_at_display: 'never', total_duration_seconds: 0 },
      scan_job: null,
    };
  }

  private isUnauthorizedError(error: unknown): boolean {
    return error instanceof HttpErrorResponse && error.status === 401;
  }

  private positionTooltip(title: string, lines: string[], clientX: number, clientY: number, w: number, h: number): UiTooltip {
    const offset = 14;
    const gap = 6;
    const margin = 8;
    const viewportWidth = typeof window === 'undefined' ? 1280 : window.innerWidth;
    const viewportHeight = typeof window === 'undefined' ? 720 : window.innerHeight;

    // Try bottom-right of cursor first
    let x = clientX + offset;
    let y = clientY + offset;

    // If overflows right, flip to left of cursor
    if (x + w > viewportWidth - margin) {
      x = clientX - w - gap;
    }
    // If overflows bottom, flip to above cursor
    if (y + h > viewportHeight - margin) {
      y = clientY - h - gap;
    }

    // Final clamp to keep within viewport
    x = Math.max(margin, Math.min(x, viewportWidth - w - margin));
    y = Math.max(margin, Math.min(y, viewportHeight - h - margin));

    return { title, lines, x, y };
  }

  private applyDashboard(dashboard: DashboardResponse): void {
    this.dataRoot.set(dashboard.settings?.data_root || '/data');
    this.summary.set(dashboard.summary);
    this.jobs.set(dashboard.jobs);
    this.inventoryState.setInventory(
      dashboard.inventory.map((row) => ({
        ...row,
        torrent_names: row.torrent_names ?? [],
        torrents_tooltip: row.torrents_tooltip ?? '',
        tracker_names: row.tracker_names ?? [],
        check_results: row.check_results ?? [],
        has_radarr: row.has_radarr ?? 0,
        has_sonarr: row.has_sonarr ?? 0,
      })),
    );
    this.meta.set(dashboard.meta);
    this.scanJob.set(dashboard.scan_job);
    this.inventoryState.setAvailableTrackers(dashboard.filters?.trackers ?? []);
    this.errorMessage.set('');
    this.isScanning.set(this.jobs().some((job) => job.state === 'running' || job.state === 'queued'));
    if (!this.isScanning()) {
      this.isStopping.set(false);
    }
  }

}
