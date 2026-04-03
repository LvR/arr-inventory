import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';

import { SessionResponse } from '../models/auth.models';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);

  session() {
    return this.http.get<SessionResponse>('/api/auth/session');
  }

  login(username: string, password: string) {
    return this.http.post<SessionResponse>('/api/auth/login', { username, password });
  }

  logout() {
    return this.http.post<SessionResponse>('/api/auth/logout', {});
  }
}
