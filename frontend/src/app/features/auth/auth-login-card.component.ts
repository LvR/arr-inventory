import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

@Component({
  selector: 'app-auth-login-card',
  standalone: true,
  templateUrl: './auth-login-card.component.html',
  styleUrl: './auth-login-card.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuthLoginCardComponent {
  readonly appName = input.required<string>();
  readonly username = input.required<string>();
  readonly password = input.required<string>();
  readonly isLoggingIn = input.required<boolean>();
  readonly authError = input.required<string>();

  readonly usernameChanged = output<string>();
  readonly passwordChanged = output<string>();
  readonly loginSubmitted = output<void>();

  onUsernameInput(event: Event): void {
    this.usernameChanged.emit((event.target as HTMLInputElement).value);
  }

  onPasswordInput(event: Event): void {
    this.passwordChanged.emit((event.target as HTMLInputElement).value);
  }
}
