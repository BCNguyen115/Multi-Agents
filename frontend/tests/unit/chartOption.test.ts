import { describe, expect, it } from 'vitest';
import { buildOption, ChartTheme, formatValue, isFilterableChart } from '../../lib/chartOption';
import type { ChartItem } from '../../lib/types';

const theme: ChartTheme = {
  palette: ['#111', '#222', '#333'], text: '#444', muted: '#555', grid: '#666', axis: '#777', surface: '#888', fg: '#999', positive: '#0a0', negative: '#a00',
};

const base = (overrides: Partial<ChartItem>): ChartItem => ({
  id: 'c1', type: 'bar', title: 'T', subtitle: '', insight: '', dimension: 'region', measure: 'revenue', aggregation: 'SUM', grain: null,
  col_span: 6, fact_ids: [], highlights: [], data: [], format: 'plain', isMonetary: false, unit: '', spec: { id: 'c1', type: 'bar', dimension: 'region' },
  ...overrides,
});

const series = (option: Record<string, unknown>) => option.series as Record<string, any>[];

describe('formatValue', () => {
  it('compacts large numbers and keeps small ones exact', () => {
    const chart = base({});
    expect(formatValue(1234567, chart)).toBe('1.2M');
    expect(formatValue(42, chart)).toBe('42');
    expect(formatValue(0.256, chart)).toBe('0.26');
    expect(formatValue(1234567.891, chart, true)).toBe('1,234,567.89');
  });

  it('renders percent measures (0..1 fractions) as percentages, but not counts', () => {
    expect(formatValue(0.1234, base({ format: 'percent', aggregation: 'AVG' }))).toBe('12.3%');
    expect(formatValue(5, base({ format: 'percent', aggregation: 'COUNT' }))).toBe('5');
  });

  it('never prints NaN', () => {
    expect(formatValue(null, base({}))).toBe('—');
    expect(formatValue(Number.NaN, base({}))).toBe('—');
  });
});

describe('isFilterableChart', () => {
  it('only category charts with a dimension can filter', () => {
    expect(isFilterableChart(base({ type: 'bar' }))).toBe(true);
    expect(isFilterableChart(base({ type: 'donut' }))).toBe(true);
    expect(isFilterableChart(base({ type: 'area', spec: { id: 'c', type: 'area' } }))).toBe(false);
    expect(isFilterableChart(base({ type: 'scatter' }))).toBe(false);
  });
});

describe('buildOption', () => {
  it('draws exactly the server numbers for a ranking, dimming unselected categories', () => {
    const data = [{ name: 'A', x: 'A', y: 30 }, { name: 'B', x: 'B', y: 20 }];
    const option = buildOption(base({ type: 'horizontal_bar', data }), theme, 'A');
    const drawn = series(option)[0].data as { value: number; itemStyle: { opacity: number } }[];
    expect(drawn.map((d) => d.value)).toEqual([30, 20]);
    expect(drawn.map((d) => d.itemStyle.opacity)).toEqual([1, 0.35]);
    expect((option.yAxis as any).data).toEqual(['A', 'B']);
    expect((option.yAxis as any).inverse).toBe(true); // largest on top
  });

  it('marks trend highlights and fills the area for area charts', () => {
    const chart = base({
      type: 'area', data: [{ x: '2024-01', y: 1 }, { x: '2024-02', y: 5 }, { x: '2024-03', y: 2 }],
      highlights: [{ type: 'max', x: '2024-02', y: 5 }, { type: 'anomaly', x: '2024-03', y: 2 }],
    });
    const line = series(buildOption(chart, theme))[0];
    expect(line.type).toBe('line');
    expect(line.areaStyle).toBeDefined();
    expect(line.markPoint.data.map((m: { name: string }) => m.name)).toEqual(['max', 'anomaly']);
  });

  it('donut slices carry their share', () => {
    const option = buildOption(base({ type: 'donut', data: [{ name: 'A', value: 75, share: 0.75 }, { name: 'B', value: 25, share: 0.25 }] }), theme);
    expect(series(option)[0].data.map((d: { share: number }) => d.share)).toEqual([0.75, 0.25]);
  });

  it('waterfall bars float on the running total', () => {
    const chart = base({
      type: 'waterfall',
      data: [{ name: 'Jan', value: 100, kind: 'total' }, { name: 'North', value: 30, kind: 'delta' }, { name: 'South', value: -10, kind: 'delta' }, { name: 'Feb', value: 120, kind: 'total' }],
    });
    const [invisible, shown] = series(buildOption(chart, theme));
    expect(invisible.data).toEqual([0, 100, 120, 0]);
    expect(shown.data.map((d: { value: number }) => d.value)).toEqual([100, 30, 10, 120]);
    expect(shown.data[1].itemStyle.color).toBe(theme.positive);
    expect(shown.data[2].itemStyle.color).toBe(theme.negative);
  });

  it('scatter groups by colour category and adds the robust trend line', () => {
    const data = [{ x: 1, y: 2, name: 'a' }, { x: 2, y: 4, name: 'b' }, { x: 3, y: 6, name: 'a' }];
    const chart = base({ type: 'scatter', data, meta: { x_label: 'X', y_label: 'Y', trend_line: { slope: 2, intercept: 0 } } });
    const all = series(buildOption(chart, theme));
    expect(all.filter((s) => s.type === 'scatter').map((s) => s.name)).toEqual(['a', 'b']);
    expect(all.find((s) => s.type === 'line')?.data).toEqual([[1, 2], [3, 6]]);
  });

  it('correlation heatmap is fixed to [-1, 1]; crosstab uses the data range', () => {
    const cells = [{ x: 'A', y: 'A', value: 1 }, { x: 'B', y: 'A', value: -0.5 }];
    const corr = buildOption(base({ type: 'heatmap', data: cells, x_data: ['A', 'B'], y_data: ['A'], meta: { kind: 'correlation' } }), theme);
    expect((corr.visualMap as any).min).toBe(-1);
    expect((corr.visualMap as any).max).toBe(1);
    expect(series(corr)[0].data).toEqual([[0, 0, 1], [1, 0, -0.5]]);
    const cross = buildOption(base({ type: 'heatmap', data: [{ x: 'A', y: 'A', value: 40 }], x_data: ['A'], y_data: ['A'], meta: { kind: 'crosstab' } }), theme);
    expect((cross.visualMap as any).max).toBe(40);
  });

  it('every chart type the backend can emit produces a series', () => {
    const types = ['line', 'area', 'bar', 'horizontal_bar', 'donut', 'scatter', 'histogram', 'heatmap', 'treemap', 'waterfall'] as const;
    for (const type of types) {
      const point = { name: 'A', x: type === 'scatter' ? 1 : 'A', y: 1, value: 1, share: 1 };
      const option = buildOption(base({ type, data: [point], x_data: ['A'], y_data: ['A'] }), theme);
      expect(series(option).length, type).toBeGreaterThan(0);
    }
  });
});
