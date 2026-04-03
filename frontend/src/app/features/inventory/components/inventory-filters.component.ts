import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { CheckFilter, FileFilter, LocationFilter } from '../../../core/models/dashboard.models';
import { checkFilterLabel, fileFilterLabel, locationFilterLabel } from '../../../core/utils/presentation.utils';

@Component({
  selector: 'app-inventory-filters',
  standalone: true,
  templateUrl: './inventory-filters.component.html',
  styleUrl: './inventory-filters.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InventoryFiltersComponent {
  readonly checkGlobalFilters = input.required<CheckFilter[]>();
  readonly checkRuleFilters = input.required<CheckFilter[]>();
  readonly locationFilters = input.required<LocationFilter[]>();
  readonly fileFilters = input.required<FileFilter[]>();
  readonly availableTrackers = input.required<string[]>();
  readonly filenameQuery = input.required<string>();
  readonly filteredTotalSizeDisplay = input.required<string>();
  readonly activeFilterCount = input.required<number>();
  readonly hasActiveFilters = input.required<boolean>();
  readonly hasCustomSort = input.required<boolean>();
  readonly activeCheckFilter = input.required<CheckFilter>();
  readonly activeLocationFilter = input.required<LocationFilter>();
  readonly activeTrackerFilter = input.required<string>();
  readonly activeFileFilter = input.required<FileFilter>();
  readonly checkFilterCounts = input.required<Record<string, number>>();
  readonly locationFilterCounts = input.required<Record<string, number>>();
  readonly trackerFilterCounts = input.required<Record<string, number>>();
  readonly fileFilterCounts = input.required<Record<string, number>>();

  readonly checkFilterSelected = output<CheckFilter>();
  readonly filenameQueryChanged = output<string>();
  readonly filenameQueryCleared = output<void>();
  readonly locationFilterSelected = output<LocationFilter>();
  readonly trackerFilterSelected = output<string>();
  readonly fileFilterSelected = output<FileFilter>();
  readonly resetFiltersClicked = output<void>();
  readonly resetSortClicked = output<void>();
  readonly resetFiltersTooltipShown = output<MouseEvent>();
  readonly resetSortTooltipShown = output<MouseEvent>();
  readonly tooltipMoved = output<MouseEvent>();
  readonly tooltipHidden = output<void>();

  onFilenameInput(event: Event): void {
    this.filenameQueryChanged.emit((event.target as HTMLInputElement).value);
  }

  labelForCheck(filter: CheckFilter): string {
    return checkFilterLabel(filter);
  }

  labelForLocation(filter: LocationFilter): string {
    return locationFilterLabel(filter);
  }

  labelForFile(filter: FileFilter): string {
    return fileFilterLabel(filter);
  }
}
