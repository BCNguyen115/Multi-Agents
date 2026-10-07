import { isUnauthorized } from './authClient';
import type { DashboardSpec, FilteredDashboard } from './types';
import { getLang, t } from './i18n';
import { apiFetch } from './apiFetch';

export type ActiveFilters = Record<string, string[]>;

/**
 * True only for a complete spec v2. Dashboards saved in the browser by an older version (v1: no `analysis`,
 * `story`, `slicers`...) must not reach the renderer, which would crash reading them.
 */
export function isDashboardSpecV2(spec: unknown): spec is DashboardSpec {
  const s = spec as Partial<DashboardSpec> | null | undefined;
  return Boolean(
    s &&
      s.version === 2 &&
      s.analysis &&
      Array.isArray(s.charts) &&
      Array.isArray(s.kpis) &&
      Array.isArray(s.slicers) &&
      s.table &&
      Array.isArray(s.table.columns) &&
      Array.isArray(s.table.rows)
  );
}

/** Toggle one value of one column (multi-select per column); empty selections are removed. */
export function toggleFilter(filters: ActiveFilters, field: string, value: string): ActiveFilters {
  const current = filters[field] ?? [];
  const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
  const { [field]: _removed, ...rest } = filters;
  return next.length ? { ...rest, [field]: next } : rest;
}

/** Recompute the dashboard's charts and KPIs on the server for the rows matching ``filters``. */
export async function filterDashboard(spec: DashboardSpec, filters: ActiveFilters, signal?: AbortSignal): Promise<FilteredDashboard> {
  if (!spec.sessionId) throw new Error('missing session');
  const response = await apiFetch('/api/analyze/filter', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: spec.sessionId,
      chart_specs: spec.charts.map((chart) => chart.spec),
      filters,
      language: spec.language,
      focus: spec.kpis.find((kpi) => kpi.id.startsWith('kpi_1_'))?.measure ?? null,
    }),
    signal,
  });
  const body = await response.json().catch(() => ({}));
  if (isUnauthorized(response)) throw new Error(t(getLang(), 'session.expired'));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${response.status}`);
  return body as FilteredDashboard;
}

/** A failed grid call: ``status`` tells "file gone" (404) from "bad filter" (422). */
export class TableError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export interface TableQuery {
  search?: string;
  slicers?: ActiveFilters;
  sort?: { field: string; dir: 'asc' | 'desc' }[];
  /** AG Grid's filter model, passed as it is. */
  columnFilters?: Record<string, unknown>;
}

export interface TablePage {
  rows: Record<string, unknown>[];
  /** Rows matching the query (all of them, not just this page). */
  total: number;
  /** Rows in the uploaded file. */
  total_all: number;
}

/** The body the backend expects for the grid's calls (a pure function: the unit test pins the wire format). */
export function tableRequestBody(spec: DashboardSpec, query: TableQuery) {
  return {
    session_id: spec.sessionId,
    search: query.search ?? '',
    sort: query.sort ?? [],
    slicers: query.slicers ?? {},
    column_filters: query.columnFilters ?? {},
  };
}

async function tableCall(path: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  const response = await apiFetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
  if (isUnauthorized(response)) throw new TableError(t(getLang(), 'session.expired'), 401);
  if (!response.ok) {
    const detail = await response.json().then((b: { detail?: unknown }) => b.detail).catch(() => undefined);
    throw new TableError(typeof detail === 'string' ? detail : `HTTP ${response.status}`, response.status);
  }
  return response;
}

/** One page of the table: every row of the uploaded file, searched, filtered and sorted on the server. */
export async function fetchTableRows(spec: DashboardSpec, query: TableQuery, start: number, limit: number, signal?: AbortSignal): Promise<TablePage> {
  if (!spec.sessionId) throw new TableError('missing session', 404);
  const response = await tableCall('/api/analyze/rows', { ...tableRequestBody(spec, query), start, limit }, signal);
  return (await response.json()) as TablePage;
}

/** Every row matching the query as a CSV file (not just the page the grid shows). */
export async function downloadTableCsv(spec: DashboardSpec, query: TableQuery): Promise<Blob> {
  if (!spec.sessionId) throw new TableError('missing session', 404);
  return (await tableCall('/api/analyze/export', tableRequestBody(spec, query))).blob();
}
