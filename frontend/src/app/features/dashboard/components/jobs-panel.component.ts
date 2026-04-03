import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { JobState, Meta } from '../../../core/models/dashboard.models';
import { jobDuration, jobHelpLines, statusLabel } from '../../../core/utils/presentation.utils';

@Component({
  selector: 'app-jobs-panel',
  standalone: true,
  templateUrl: './jobs-panel.component.html',
  styleUrl: './jobs-panel.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class JobsPanelComponent {
  readonly jobs = input.required<JobState[]>();
  readonly meta = input.required<Meta>();
  readonly totalJobs = input.required<number>();
  readonly completedJobsCount = input.required<number>();
  readonly totalDuration = input.required<string>();

  readonly jobHelpShown = output<{ event: MouseEvent; title: string; lines: string[] }>();
  readonly tooltipMoved = output<MouseEvent>();
  readonly tooltipHidden = output<void>();

  onJobHelpEnter(event: MouseEvent, job: JobState): void {
    this.jobHelpShown.emit({ event, title: job.label, lines: jobHelpLines(job.job_key) });
  }

  statusLabel(state: string | undefined): string {
    return statusLabel(state);
  }

  jobDuration(job: JobState): string {
    return jobDuration(job);
  }
}
