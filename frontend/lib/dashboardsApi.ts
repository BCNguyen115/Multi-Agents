import { isUnauthorized } from './authClient';
import type { DashboardSpec } from './types';
import { getLang, t } from './i18n';
import { apiFetch } from './apiFetch';

/** One saved dashboard as the list shows it (no spec): `mine` is false for one a colleague of the tenant shared. */
export interface SavedDashboard {
  id: string;
  title: string;
  filename: string;
  shared: boolean;
  mine: boolean;
  updated_at: string;
}

/** A saved dashboard opened: its spec comes with a `sessionId` whose file is back on the server (filters and the grid work). */
export interface OpenedDashboard extends SavedDashboard {
  spec: DashboardSpec;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(`/api/dashboards${path}`, init);
  if (isUnauthorized(response)) throw new Error(t(getLang(), 'session.expired'));
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${response.status}`);
  return body as T;
}

const json = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export const listDashboards = () => call<SavedDashboard[]>('');
export const saveDashboard = (spec: DashboardSpec, title: string) => call<SavedDashboard>('', json('POST', { title, session_id: spec.sessionId, spec }));
export const openDashboard = (id: string) => call<OpenedDashboard>(`/${encodeURIComponent(id)}/open`, { method: 'POST' });
export const refreshDashboard = (id: string) => call<OpenedDashboard>(`/${encodeURIComponent(id)}/refresh`, { method: 'POST' });
export const patchDashboard = (id: string, changes: { title?: string; shared?: boolean }) => call<SavedDashboard>(`/${encodeURIComponent(id)}`, json('PATCH', changes));
export const deleteDashboard = (id: string) => call<void>(`/${encodeURIComponent(id)}`, { method: 'DELETE' });
