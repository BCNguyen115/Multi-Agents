/** Browser side of the login: who am I, sign out, and "send me to the login screen when the session is gone". */

export interface Me {
  authenticated: boolean; // false = the backend runs with AUTH_MODE=off (anonymous): there is nothing to sign in to
  user: string;
  name?: string; // display name; empty for accounts that have none
  tenant_id: string;
  department_id: string;
  roles: string[];
  can_approve: boolean;
  can_manage_knowledge: boolean;
  /** Sensitive actions need a SECOND person: the requester waits, approvers have an inbox. */
  two_person_approval?: boolean;
  /** A fresh sign-up: chat works, documents and database rows come after an administrator grants access. */
  access_pending?: boolean;
}

export const LOGIN_PATH = '/login';

/** What the sign-in dialog may offer; both false when the backend has no built-in sign-in (anonymous dev mode or an identity provider). */
export interface AuthConfig {
  login_enabled: boolean;
  registration_enabled: boolean;
}

export const NO_AUTH: AuthConfig = { login_enabled: false, registration_enabled: false };

// The AuthProvider registers itself here, so "the session is gone" opens the sign-in dialog instead of leaving the page.
let authRequiredHandler: (() => void) | null = null;
export function setAuthRequiredHandler(handler: (() => void) | null): void {
  authRequiredHandler = handler;
}

export function redirectToLogin(): void {
  if (authRequiredHandler) {
    authRequiredHandler();
    return;
  }
  if (typeof window !== 'undefined' && window.location.pathname !== LOGIN_PATH) {
    window.location.assign(LOGIN_PATH);
  }
}

export async function fetchAuthConfig(): Promise<AuthConfig> {
  try {
    const response = await fetch('/api/auth/config', { cache: 'no-store' });
    return response.ok ? ((await response.json()) as AuthConfig) : NO_AUTH;
  } catch {
    return NO_AUTH;
  }
}

/** Ends the session on the server side only (the cookie); the caller decides what the page does next. */
export async function logoutRequest(): Promise<void> {
  await fetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined);
}

/** True (and the browser is sent to the login screen) when the backend answered 401: the token is missing or expired. */
export function isUnauthorized(response: { status: number }): boolean {
  if (response.status !== 401) return false;
  redirectToLogin();
  return true;
}

/** The signed-in user, `null` when there is no valid session (401), and throws when the backend cannot be reached. */
export async function fetchMe(): Promise<Me | null> {
  const response = await fetch('/api/auth/me', { cache: 'no-store' });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as Me;
}

export async function logout(): Promise<void> {
  await fetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined);
  redirectToLogin();
}
