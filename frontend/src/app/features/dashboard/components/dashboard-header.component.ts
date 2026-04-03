import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { Summary } from '../../../core/models/dashboard.models';

@Component({
  selector: 'app-dashboard-header',
  standalone: true,
  templateUrl: './dashboard-header.component.html',
  styleUrl: './dashboard-header.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardHeaderComponent {
  readonly appName = input.required<string>();
  readonly summary = input.required<Summary>();
  readonly authUsername = input.required<string>();
  readonly analysisInProgress = input.required<boolean>();
  readonly isPurging = input.required<boolean>();
  readonly isScanning = input.required<boolean>();

  readonly logoutClicked = output<void>();
  readonly startScanClicked = output<void>();
  readonly stopScanClicked = output<void>();
  readonly purgeInventoryClicked = output<void>();
  readonly logoutTooltipShown = output<MouseEvent>();
  readonly startScanTooltipShown = output<MouseEvent>();
  readonly stopScanTooltipShown = output<MouseEvent>();
  readonly purgeInventoryTooltipShown = output<MouseEvent>();
  readonly tooltipMoved = output<MouseEvent>();
  readonly tooltipHidden = output<void>();
}
