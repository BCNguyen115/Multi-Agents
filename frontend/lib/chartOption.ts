/**
 * Pure ECharts option builder for the chart shapes the data agent emits (spec v2).
 *
 * The server has already computed every number; this module only decides how to draw them. It never
 * looks at column names and never aggregates: what is in ``chart.data`` is what is shown.
 */

import type { ChartItem, ChartPoint } from './types';

export interface ChartTheme {
  palette: string[];
  text: string;
  muted: string;
  grid: string;
  axis: string;
  surface: string;
  fg: string;
  positive: string;
  negative: string;
}

export type EChartsOptionLike = Record<string, unknown>;

const compact = (value: number): string => {
  const abs = Math.abs(value);
  const scaled = (divisor: number, suffix: string) => `${trim((value / divisor).toFixed(abs / divisor >= 100 ? 0 : 1))}${suffix}`;
  if (abs >= 1e12) return scaled(1e12, 'T');
  if (abs >= 1e9) return scaled(1e9, 'B');
  if (abs >= 1e6) return scaled(1e6, 'M');
  if (abs >= 1e4) return scaled(1e3, 'K');
  return Number.isInteger(value) ? value.toLocaleString('en-US') : trim(value.toFixed(2));
};

const trim = (text: string): string => (text.includes('.') ? text.replace(/\.?0+$/, '') : text);

/** Value as shown on axes and in tooltips; percent measures are stored as 0..1 fractions. */
export function formatValue(value: unknown, chart: Pick<ChartItem, 'format' | 'aggregation'>, full = false): string {
  const number = typeof value === 'number' ? value : Number(value);
  if (value === null || value === undefined || value === '' || !Number.isFinite(number)) return '—';
  if (chart.format === 'percent' && chart.aggregation !== 'COUNT') return `${trim((number * 100).toFixed(1))}%`;
  return full ? number.toLocaleString('en-US', { maximumFractionDigits: 2 }) : compact(number);
}

/** Charts whose categories can be clicked to filter the dashboard. */
export function isFilterableChart(chart: ChartItem): boolean {
  return Boolean(chart.spec?.dimension) && ['bar', 'horizontal_bar', 'donut', 'treemap'].includes(chart.type);
}

const label = (point: ChartPoint): string => String(point.name ?? point.x ?? '');
const numeric = (value: unknown): number => (typeof value === 'number' && Number.isFinite(value) ? value : 0);

function tooltipBase(theme: ChartTheme) {
  return {
    backgroundColor: theme.surface,
    borderColor: theme.axis,
    borderWidth: 1,
    textStyle: { color: theme.fg, fontSize: 12 },
  };
}

function categoryAxis(names: string[], theme: ChartTheme, extra: Record<string, unknown> = {}) {
  return {
    type: 'category',
    data: names,
    axisLabel: { color: theme.text, fontSize: 10, hideOverlap: true, formatter: (v: string) => (v.length > 14 ? `${v.slice(0, 13)}…` : v) },
    axisLine: { lineStyle: { color: theme.axis } },
    axisTick: { show: false },
    ...extra,
  };
}

function valueAxis(chart: ChartItem, theme: ChartTheme, extra: Record<string, unknown> = {}) {
  return {
    type: 'value',
    axisLabel: { color: theme.text, fontSize: 10, formatter: (v: number) => formatValue(v, chart) },
    splitLine: { lineStyle: { type: 'dashed', color: theme.grid } },
    ...extra,
  };
}

const dim = (selected: string | null | undefined, name: string): number => (selected && selected !== name ? 0.35 : 1);

// ---------------------------------------------------------------------------
// One builder per chart type
// ---------------------------------------------------------------------------

function trend(chart: ChartItem, theme: ChartTheme): EChartsOptionLike {
  const names = chart.data.map(label);
  const color = theme.palette[0];
  const marks = chart.highlights.map((h) => ({
    name: h.type,
    coord: [h.x, h.y],
    value: formatValue(h.y, chart),
    itemStyle: { color: h.type === 'anomaly' ? theme.negative : h.type === 'max' ? theme.positive : theme.muted },
    symbolSize: h.type === 'anomaly' ? 44 : 34,
  }));
  return {
    tooltip: { ...tooltipBase(theme), trigger: 'axis', valueFormatter: (v: unknown) => formatValue(v, chart, true) },
    grid: { left: 8, right: 16, top: 24, bottom: 28, containLabel: true },
    xAxis: categoryAxis(names, theme, { boundaryGap: false }),
    yAxis: valueAxis(chart, theme),
    series: [
      {
        type: 'line',
        smooth: 0.25,
        showSymbol: names.length <= 24,
        data: chart.data.map((d) => d.y ?? null),
        lineStyle: { width: 2.5, color },
        itemStyle: { color },
        areaStyle: chart.type === 'area' ? { color, opacity: 0.16 } : undefined,
        markPoint: marks.length ? { data: marks, label: { color: '#fff', fontSize: 10 } } : undefined,
      },
    ],
    dataZoom: names.length > 60 ? [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 4 }] : undefined,
  };
}

function bars(chart: ChartItem, theme: ChartTheme, selected?: string | null): EChartsOptionLike {
  const horizontal = chart.type === 'horizontal_bar';
  const names = chart.data.map(label);
  const series = {
    type: 'bar',
    barMaxWidth: 34,
    data: chart.data.map((d) => ({
      value: d.y ?? null,
      itemStyle: { color: theme.palette[0], opacity: dim(selected, label(d)), borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0] },
    })),
    label: chart.data.length <= 8 ? { show: true, position: horizontal ? 'right' : 'top', color: theme.text, fontSize: 10, formatter: (p: { value: unknown }) => formatValue(p.value, chart) } : undefined,
  };
  return {
    tooltip: {
      ...tooltipBase(theme),
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (v: unknown) => formatValue(v, chart, true),
    },
    grid: { left: 8, right: 24, top: 24, bottom: 8, containLabel: true },
    xAxis: horizontal ? valueAxis(chart, theme) : categoryAxis(names, theme, { axisLabel: { color: theme.text, fontSize: 10, interval: 0, rotate: names.length > 6 ? 30 : 0, formatter: (v: string) => (v.length > 14 ? `${v.slice(0, 13)}…` : v) } }),
    yAxis: horizontal ? categoryAxis(names, theme, { inverse: true }) : valueAxis(chart, theme),
    series: [series],
  };
}

function donut(chart: ChartItem, theme: ChartTheme, selected?: string | null): EChartsOptionLike {
  return {
    tooltip: {
      ...tooltipBase(theme),
      trigger: 'item',
      formatter: (p: { name: string; value: number; data: { share?: number | null } }) =>
        `${p.name}<br/><b>${formatValue(p.value, chart, true)}</b> · ${trim(((p.data.share ?? 0) * 100).toFixed(1))}%`,
    },
    legend: { bottom: 0, type: 'scroll', textStyle: { color: theme.text, fontSize: 10 } },
    color: theme.palette,
    series: [
      {
        type: 'pie',
        radius: ['46%', '72%'],
        center: ['50%', '44%'],
        minAngle: 4,
        itemStyle: { borderColor: theme.surface, borderWidth: 2, borderRadius: 5 },
        label: { color: theme.text, fontSize: 10, formatter: (p: { name: string; data: { share?: number | null } }) => `${p.name}\n${trim(((p.data.share ?? 0) * 100).toFixed(1))}%` },
        data: chart.data.map((d) => ({ name: label(d), value: numeric(d.value), share: d.share, itemStyle: { opacity: dim(selected, label(d)) } })),
      },
    ],
  };
}

function treemap(chart: ChartItem, theme: ChartTheme): EChartsOptionLike {
  return {
    tooltip: { ...tooltipBase(theme), formatter: (p: { name: string; value: number }) => `${p.name}<br/><b>${formatValue(p.value, chart, true)}</b>` },
    color: theme.palette,
    series: [
      {
        type: 'treemap',
        roam: false,
        breadcrumb: { show: false },
        nodeClick: false,
        label: { fontSize: 11, formatter: '{b}' },
        itemStyle: { borderColor: theme.surface, borderWidth: 2, gapWidth: 2 },
        data: chart.data.map((d) => ({ name: label(d), value: numeric(d.value) })),
      },
    ],
  };
}

function histogram(chart: ChartItem, theme: ChartTheme): EChartsOptionLike {
  const names = chart.data.map(label);
  return {
    tooltip: { ...tooltipBase(theme), trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    xAxis: categoryAxis(names, theme, { axisLabel: { color: theme.text, fontSize: 9, rotate: 35, hideOverlap: true } }),
    yAxis: { ...valueAxis(chart, theme), axisLabel: { color: theme.text, fontSize: 10 } },
    series: [{ type: 'bar', barCategoryGap: '4%', data: chart.data.map((d) => d.y ?? 0), itemStyle: { color: theme.palette[0] } }],
  };
}

function scatter(chart: ChartItem, theme: ChartTheme): EChartsOptionLike {
  const groups = new Map<string, [number, number][]>();
  for (const d of chart.data) {
    if (typeof d.x !== 'number' || typeof d.y !== 'number') continue;
    const key = d.name ?? '';
    groups.set(key, [...(groups.get(key) ?? []), [d.x, d.y]]);
  }
  const xs = chart.data.map((d) => d.x).filter((v): v is number => typeof v === 'number');
  const line = chart.meta?.trend_line;
  const trendSeries =
    line && line.slope !== null && line.intercept !== null && xs.length
      ? [{ type: 'line', symbol: 'none', silent: true, lineStyle: { color: theme.muted, type: 'dashed', width: 1.5 }, data: [Math.min(...xs), Math.max(...xs)].map((x) => [x, line.slope! * x + line.intercept!]) }]
      : [];
  return {
    tooltip: { ...tooltipBase(theme), trigger: 'item', formatter: (p: { value: number[]; seriesName: string }) => `${p.seriesName ? `${p.seriesName}<br/>` : ''}${chart.meta?.x_label}: ${formatValue(p.value[0], chart, true)}<br/>${chart.meta?.y_label}: ${formatValue(p.value[1], chart, true)}` },
    color: theme.palette,
    legend: groups.size > 1 ? { top: 0, type: 'scroll', textStyle: { color: theme.text, fontSize: 10 } } : undefined,
    grid: { left: 8, right: 16, top: groups.size > 1 ? 32 : 20, bottom: 24, containLabel: true },
    xAxis: { ...valueAxis(chart, theme), scale: true, name: chart.meta?.x_label, nameLocation: 'middle', nameGap: 26, nameTextStyle: { color: theme.text, fontSize: 10 } },
    yAxis: { ...valueAxis(chart, theme), scale: true, name: chart.meta?.y_label, nameTextStyle: { color: theme.text, fontSize: 10 } },
    series: [
      ...[...groups].map(([name, points]) => ({ type: 'scatter', name, symbolSize: 6, data: points, itemStyle: { opacity: 0.6 } })),
      ...trendSeries,
    ],
  };
}

function heatmap(chart: ChartItem, theme: ChartTheme): EChartsOptionLike {
  const xs = chart.x_data ?? [];
  const ys = chart.y_data ?? [];
  const correlation = chart.meta?.kind === 'correlation';
  const values = chart.data.map((d) => numeric(d.value));
  const cells = chart.data.map((d) => [xs.indexOf(String(d.x)), ys.indexOf(String(d.y)), d.value ?? 0]);
  return {
    tooltip: { ...tooltipBase(theme), formatter: (p: { value: [number, number, number] }) => `${ys[p.value[1]]} × ${xs[p.value[0]]}<br/><b>${correlation ? trim(p.value[2].toFixed(2)) : formatValue(p.value[2], chart, true)}</b>` },
    grid: { left: 8, right: 16, top: 12, bottom: 56, containLabel: true },
    xAxis: categoryAxis(xs, theme, { splitArea: { show: true }, axisLabel: { color: theme.text, fontSize: 10, interval: 0, rotate: 30 } }),
    yAxis: categoryAxis(ys, theme, { splitArea: { show: true } }),
    visualMap: {
      min: correlation ? -1 : Math.min(0, ...values),
      max: correlation ? 1 : Math.max(1, ...values),
      calculable: false,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemHeight: 90,
      textStyle: { color: theme.text, fontSize: 10 },
      inRange: { color: correlation ? [theme.negative, theme.surface, theme.positive] : [theme.surface, theme.palette[0]] },
    },
    series: [{ type: 'heatmap', data: cells, label: { show: cells.length <= 64, fontSize: 9, formatter: (p: { value: [number, number, number] }) => (correlation ? trim(p.value[2].toFixed(2)) : formatValue(p.value[2], chart)) } }],
  };
}

function waterfall(chart: ChartItem, theme: ChartTheme): EChartsOptionLike {
  const names = chart.data.map(label);
  let running = 0;
  const base: number[] = [];
  const shown: { value: number; itemStyle: { color: string } }[] = [];
  for (const row of chart.data) {
    const value = numeric(row.value);
    if (row.kind === 'total') {
      running = value;
      base.push(0);
      shown.push({ value, itemStyle: { color: theme.palette[0] } });
    } else {
      const next = running + value;
      base.push(Math.min(running, next));
      shown.push({ value: Math.abs(value), itemStyle: { color: value >= 0 ? theme.positive : theme.negative } });
      running = next;
    }
  }
  return {
    tooltip: {
      ...tooltipBase(theme),
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: { dataIndex: number }[]) => {
        const row = chart.data[params[0].dataIndex];
        const sign = row.kind === 'delta' && numeric(row.value) > 0 ? '+' : '';
        return `${label(row)}<br/><b>${sign}${formatValue(row.value, chart, true)}</b>`;
      },
    },
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    xAxis: categoryAxis(names, theme),
    yAxis: valueAxis(chart, theme),
    series: [
      { type: 'bar', stack: 'wf', silent: true, itemStyle: { color: 'transparent' }, data: base },
      { type: 'bar', stack: 'wf', barMaxWidth: 38, data: shown },
    ],
  };
}

/** ECharts option for a server-computed chart. ``selected`` dims every other category (active cross-filter). */
export function buildOption(chart: ChartItem, theme: ChartTheme, selected?: string | null): EChartsOptionLike {
  switch (chart.type) {
    case 'line':
    case 'area':
      return trend(chart, theme);
    case 'bar':
    case 'horizontal_bar':
      return bars(chart, theme, selected);
    case 'donut':
      return donut(chart, theme, selected);
    case 'treemap':
      return treemap(chart, theme);
    case 'histogram':
      return histogram(chart, theme);
    case 'scatter':
      return scatter(chart, theme);
    case 'heatmap':
      return heatmap(chart, theme);
    case 'waterfall':
      return waterfall(chart, theme);
    default:
      return { title: { text: chart.title } };
  }
}
