import { redirectToLogin } from './authClient';
import { getLang } from './i18n';

/**
 * `fetch` for this app's own `/api/*` routes: it adds `X-UI-Lang`, so the messages the backend writes (errors, upload
 * summaries) come back in the language the user chose in the interface. A 401 (the session is gone or expired) opens the
 * sign-in dialog for every caller; `/api/auth/*` is exempt because a wrong password also answers 401 there.
 * Everything else behaves like `fetch`.
 */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('X-UI-Lang', getLang());
  const response = await fetch(input, { ...init, headers });
  if (response.status === 401 && !input.startsWith('/api/auth/')) redirectToLogin();
  return response;
}
