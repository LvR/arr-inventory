export interface SessionResponse {
  authenticated: boolean;
  username?: string;
}

export function anonymousSessionState(): SessionResponse {
  return { authenticated: false };
}
