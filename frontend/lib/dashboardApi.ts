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
