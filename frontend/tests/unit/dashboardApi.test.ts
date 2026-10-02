import { afterEach, describe, expect, it, vi } from 'vitest';
import { filterDashboard, toggleFilter } from '../../lib/dashboardApi';
import type { DashboardSpec } from '../../lib/types';

const spec = {
  sessionId: 's1', language: 'vi',
  kpis: [{ id: 'kpi_records', measure: null }, { id: 'kpi_1_sum', measure: 'revenue' }],
  charts: [{ spec: { id: 'c1', type: 'bar', dimension: 'region' } }, { spec: { id: 'c2', type: 'area' } }],
} as unknown as DashboardSpec;

afterEach(() => vi.unstubAllGlobals());

describe('toggleFilter', () => {
  it('adds, removes and drops empty selections without mutating the input', () => {
    const start = { region: ['North'] };
    const two = toggleFilter(start, 'region', 'East');
    expect(two).toEqual({ region: ['North', 'East'] });
    expect(start).toEqual({ region: ['North'] });
    expect(toggleFilter(two, 'region', 'North')).toEqual({ region: ['East'] });
    expect(toggleFilter({ region: ['East'] }, 'region', 'East')).toEqual({});
    expect(toggleFilter({ region: ['East'] }, 'channel', 'online')).toEqual({ region: ['East'], channel: ['online'] });
  });
});

describe('filterDashboard', () => {
  it('posts the chart specs, filters and language for the session', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ rows_used: 3, rows_total: 9, charts: [], kpis: [], verified: true }) });
    vi.stubGlobal('fetch', fetchMock);
    const result = await filterDashboard(spec, { region: ['North'] });
    expect(result.rows_used).toBe(3);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/analyze/filter');
    expect(JSON.parse(init.body)).toEqual({
      session_id: 's1', chart_specs: [{ id: 'c1', type: 'bar', dimension: 'region' }, { id: 'c2', type: 'area' }], filters: { region: ['North'] }, language: 'vi', focus: 'revenue',
    });
  });

  it('surfaces the backend explanation on errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: 'Không có dữ liệu' }) }));
    await expect(filterDashboard(spec, { region: ['North'] })).rejects.toThrow('Không có dữ liệu');
  });

  it('refuses to call the server without a session', async () => {
    await expect(filterDashboard({ ...spec, sessionId: undefined } as DashboardSpec, {})).rejects.toThrow('missing session');
  });
});
