import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { CheckStatus, InventoryRow, SortDirection, SortKey } from '../../../core/models/dashboard.models';
import { checkTooltipLines, consistencyBadgeClass, consistencyBadgeLabel, fileTypeBadgeClass, torrentBadge } from '../../../core/utils/presentation.utils';

@Component({
  selector: 'app-inventory-table',
  standalone: true,
  templateUrl: './inventory-table.component.html',
  styleUrl: './inventory-table.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InventoryTableComponent {
  readonly tableHeaders = input.required<Array<{ key: SortKey; label: string }>>();
  readonly rows = input.required<InventoryRow[]>();
  readonly sortKey = input.required<SortKey>();
  readonly sortDirection = input.required<SortDirection>();

  readonly sortRequested = output<SortKey>();
  readonly rowSelected = output<number>();
  readonly checkTooltipShown = output<{ event: MouseEvent; lines: string[] }>();
  readonly trackerTooltipShown = output<{ event: MouseEvent; lines: string[] }>();
  readonly tooltipMoved = output<MouseEvent>();
  readonly tooltipHidden = output<void>();

  onHeaderKeydown(event: KeyboardEvent, key: SortKey): void {
    if (event.key !== 'Enter' && event.key !== ' ') {
      return;
    }
    event.preventDefault();
    this.sortRequested.emit(key);
  }

  onCheckEnter(event: MouseEvent, row: InventoryRow): void {
    if (row.consistency_status !== 'ko' && row.consistency_status !== 'ok') {
      return;
    }
    this.checkTooltipShown.emit({ event, lines: checkTooltipLines(row) });
  }

  onTrackerEnter(event: MouseEvent, row: InventoryRow): void {
    this.trackerTooltipShown.emit({ event, lines: row.tracker_names.length ? row.tracker_names : ['No tracker'] });
  }

  isSorted(key: SortKey): boolean {
    return this.sortKey() === key;
  }

  sortDirectionFor(key: SortKey): SortDirection | '' {
    return this.sortKey() === key ? this.sortDirection() : '';
  }

  consistencyBadgeClass(status: CheckStatus): string {
    return consistencyBadgeClass(status);
  }

  consistencyBadgeLabel(status: CheckStatus): string {
    return consistencyBadgeLabel(status);
  }

  torrentBadge(row: InventoryRow): string {
    return torrentBadge(row);
  }

  fileTypeBadgeClass(fileType: InventoryRow['file_type']): string {
    return fileTypeBadgeClass(fileType);
  }
}
