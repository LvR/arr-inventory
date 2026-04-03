export interface SessionResponse {
  authenticated: boolean;
  username?: string;
  app_version?: string;
}

export function anonymousSessionState(): SessionResponse {
  return { authenticated: false, app_version: '' };
}
