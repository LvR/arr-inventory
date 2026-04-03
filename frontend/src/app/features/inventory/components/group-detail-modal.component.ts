import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { CheckStatus, GroupDetail } from '../../../core/models/dashboard.models';
import {
  checkResultClass,
  consistencyBadgeClass,
  consistencyBadgeLabel,
  humanBytes,
  humanSeconds,
  torrentStatusClass,
  torrentStatusLabel,
  trackerNamesLine,
  trackerStatusClass,
  trackerStatusLabel,
} from '../../../core/utils/presentation.utils';

@Component({
  selector: 'app-group-detail-modal',
  standalone: true,
  templateUrl: './group-detail-modal.component.html',
  styleUrl: './group-detail-modal.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GroupDetailModalComponent {
  readonly detail = input.required<GroupDetail>();

  readonly closeRequested = output<void>();
  readonly copyPathRequested = output<{ path: string; event: MouseEvent }>();

  requestCopy(path: string, event: MouseEvent): void {
    this.copyPathRequested.emit({ path, event });
  }

  consistencyBadgeClass(status: CheckStatus): string {
    return consistencyBadgeClass(status);
  }

  consistencyBadgeLabel(status: CheckStatus): string {
    return consistencyBadgeLabel(status);
  }

  checkResultClass(status: CheckStatus): string {
    return checkResultClass(status);
  }

  torrentStatusClass(status: string): string {
    return torrentStatusClass(status);
  }

  torrentStatusLabel(status: string): string {
    return torrentStatusLabel(status);
  }

  trackerStatusClass(status: string): string {
    return trackerStatusClass(status);
  }

  trackerStatusLabel(status: string): string {
    return trackerStatusLabel(status);
  }

  trackerNamesLine(trackerNames: string[]): string {
    return trackerNamesLine(trackerNames);
  }

  humanBytes(value: number): string {
    return humanBytes(value);
  }

  humanSeconds(value: number): string {
    return humanSeconds(value);
  }
}
