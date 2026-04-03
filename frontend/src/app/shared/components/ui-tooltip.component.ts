import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { UiTooltip } from '../../core/models/dashboard.models';

@Component({
  selector: 'app-ui-tooltip',
  standalone: true,
  templateUrl: './ui-tooltip.component.html',
  styleUrl: './ui-tooltip.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UiTooltipComponent {
  readonly tooltip = input.required<UiTooltip>();
}
