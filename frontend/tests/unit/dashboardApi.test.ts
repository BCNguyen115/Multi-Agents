import { afterEach, describe, expect, it, vi } from 'vitest';
import { TableError, downloadTableCsv, fetchTableRows, filterDashboard, tableRequestBody, toggleFilter } from '../../lib/dashboardApi';
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

describe('the grid asks the server for its rows (every row of the upload, not a preview)', () => {
  const query = { search: 'abc', slicers: { region: ['North'] }, sort: [{ field: 'revenue', dir: 'desc' as const }], columnFilters: { region: { filterType: 'text', type: 'equals', filter: 'x' } } };

  it('sends the session, search, slicers, sort and AG Grid filter model with the page range', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ rows: [{ a: 1 }], total: 40, total_all: 8807 }) });
    vi.stubGlobal('fetch', fetchMock);
    const page = await fetchTableRows(spec, query, 100, 50);
    expect(page).toEqual({ rows: [{ a: 1 }], total: 40, total_all: 8807 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/analyze/rows');
    expect(JSON.parse(init.body)).toEqual({
      session_id: 's1', search: 'abc', sort: [{ field: 'revenue', dir: 'desc' }], slicers: { region: ['North'] },
      column_filters: { region: { filterType: 'text', type: 'equals', filter: 'x' } }, start: 100, limit: 50,
    });
  });

  it('defaults an empty query to "everything, in file order"', () => {
    expect(tableRequestBody(spec, {})).toEqual({ session_id: 's1', search: '', sort: [], slicers: {}, column_filters: {} });
  });

  it('tells "the file is gone" (404) from "bad filter" (422) by status, with the backend explanation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: 'Không có dữ liệu' }) }));
    await expect(fetchTableRows(spec, {}, 0, 100)).rejects.toMatchObject({ status: 404, message: 'Không có dữ liệu' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({}) }));
    const error = await fetchTableRows(spec, {}, 0, 100).catch((e) => e);
    expect(error).toBeInstanceOf(TableError);
    expect(error).toMatchObject({ status: 422, message: 'HTTP 422' });
  });

  it('downloads every matching row as one CSV file', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, blob: async () => new Blob(['a,b\n1,2\n']) });
    vi.stubGlobal('fetch', fetchMock);
    const blob = await downloadTableCsv(spec, query);
    expect(await blob.text()).toBe('a,b\n1,2\n');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/analyze/export');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).not.toHaveProperty('start'); // the whole result, not a page
  });

  it('refuses to call the server without a session', async () => {
    const without = { ...spec, sessionId: undefined } as DashboardSpec;
    await expect(fetchTableRows(without, {}, 0, 10)).rejects.toMatchObject({ status: 404 });
    await expect(downloadTableCsv(without, {})).rejects.toMatchObject({ status: 404 });
  });
});
