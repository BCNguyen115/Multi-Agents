import { getLang } from './i18n';

/**
 * `fetch` for this app's own `/api/*` routes: it adds `X-UI-Lang`, so the messages the backend writes (errors, upload
 * summaries) come back in the language the user chose in the interface. Everything else behaves like `fetch`.
 */
export function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('X-UI-Lang', getLang());
  return fetch(input, { ...init, headers });
}
