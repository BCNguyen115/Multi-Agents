/**
 * EXPORT ENGINE
 * 1. PDF: browser print dialog with the print stylesheet.
 * 2. PPTX: 16:9 deck built from the verified dashboard spec (story, KPIs, native charts, caveats).
 *
 * Every number in the deck is read from the spec; nothing is recomputed or invented here.
 */

import type { ChartItem, DashboardSpec, FilteredDashboard } from './types';
import { formatValue } from './chartOption';
import { isDashboardSpecV2 } from './dashboardApi';
import { ui } from './uiText';
import { getLang, t as translate } from './i18n';

export function exportDashboardToPDF() {
  if (typeof window === 'undefined') return;
  window.print();
}

const COLORS = {
  bg: '090D16',
  card: '181E2C',
  text: 'FFFFFF',
  muted: '94A3B8',
  blue: '3B82F6',
  green: '10B981',
  amber: 'F59E0B',
  red: 'F43F5E',
  border: '27354A',
  series: ['3B82F6', '10B981', 'F59E0B', '6366F1', 'F43F5E', '06B6D4', '8B5CF6'],
};
const MAX_POINTS = 12;
const NATIVE_TYPES = new Set(['bar', 'horizontal_bar', 'line', 'area', 'donut', 'histogram', 'treemap']);

const safeName = (name: string) => name.replace(/\.[^/.]+$/, '').replace(/[^\p{L}\p{N}\s-]/gu, '').replace(/\s+/g, '_') || 'Dashboard';

export async function exportDashboardToPPTX(spec: DashboardSpec, view?: FilteredDashboard | null): Promise<void> {
  if (typeof window === 'undefined') return;
  if (!isDashboardSpecV2(spec)) throw new Error(translate(getLang(), 'export.legacy'));
  const t = (key: Parameters<typeof ui>[1], params?: Record<string, string | number>) => ui(spec.language, key, params);

  const PptxGenJS = (await import('pptxgenjs')).default;
  const pres = new PptxGenJS();
  pres.layout = 'LAYOUT_16x9';

  const slide = (title: string, subtitle?: string) => {
    const s = pres.addSlide();
    s.background = { color: COLORS.bg };
    s.addText(title, { x: 0.6, y: 0.4, w: 12.1, h: 0.6, fontSize: 20, bold: true, color: COLORS.text, fit: 'shrink' });
    if (subtitle) s.addText(subtitle, { x: 0.6, y: 1.0, w: 12.1, h: 0.4, fontSize: 11, color: COLORS.muted, fit: 'shrink' });
    return s;
  };

  // Cover
  const cover = pres.addSlide();
  cover.background = { color: COLORS.bg };
  cover.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: 13.33, h: 0.15, fill: { color: COLORS.blue } });
  cover.addText(spec.title, { x: 1, y: 2.3, w: 11.3, h: 1.4, fontSize: 28, bold: true, color: COLORS.text, valign: 'top', fit: 'shrink' });
  cover.addText(t('cover'), { x: 1, y: 3.8, w: 11.3, h: 0.5, fontSize: 14, color: COLORS.muted });
  const rowsUsed = view ? view.rows_used : spec.analysis.rows_used;
  cover.addText(
    [
      { text: `${rowsUsed.toLocaleString('en-US')} ${t('of')} ${spec.analysis.rows_total.toLocaleString('en-US')} ${t('rows')}  |  ${spec.table.columns.length} ${t('columns')}  |  `, options: { color: COLORS.text } },
      spec.verified === false || (view && !view.verified)
        ? { text: t('unverified'), options: { color: COLORS.amber, bold: true } }
        : { text: t('verified'), options: { color: COLORS.green, bold: true } },
    ],
    { x: 1, y: 5.3, w: 11.3, h: 0.6, fontSize: 12 }
  );
  if (spec.analysis.sampled) {
    cover.addText(t('sampled', { used: spec.analysis.rows_used.toLocaleString('en-US'), total: spec.analysis.rows_total.toLocaleString('en-US') }), {
      x: 1, y: 5.9, w: 11.3, h: 0.4, fontSize: 10, color: COLORS.amber,
    });
  }

  // Story (findings describe the full dataset even when a filter is active)
  const story = spec.story;
  if (story && spec.mode !== 'single_chart') {
    const s = slide(t('story'), story.headline);
    const paragraphs: { text: string; options: Record<string, unknown> }[] = [];
    story.sections.forEach((section) => {
      paragraphs.push({ text: section.title, options: { bold: true, color: COLORS.blue, fontSize: 12, breakLine: true } });
      section.items.forEach((item) => paragraphs.push({ text: item.text, options: { bullet: true, color: COLORS.text, fontSize: 10.5, breakLine: true } }));
    });
    s.addText(paragraphs, { x: 0.6, y: 1.6, w: 12.1, h: 5.4, valign: 'top', fit: 'shrink' });

    if (story.actions.length || story.caveats.length) {
      const s2 = slide(`${t('actions')} · ${t('watch')}`, story.hypothesis_note || undefined);
      const rest: { text: string; options: Record<string, unknown> }[] = [];
      if (story.actions.length) rest.push({ text: t('actions'), options: { bold: true, color: COLORS.green, fontSize: 12, breakLine: true } });
      story.actions.forEach((a) => rest.push({ text: a.text, options: { bullet: true, color: COLORS.text, fontSize: 10.5, breakLine: true } }));
      if (story.caveats.length) rest.push({ text: t('watch'), options: { bold: true, color: COLORS.amber, fontSize: 12, breakLine: true } });
      story.caveats.forEach((c) => rest.push({ text: c.text, options: { bullet: true, color: COLORS.text, fontSize: 10.5, breakLine: true } }));
      s2.addText(rest, { x: 0.6, y: 1.6, w: 12.1, h: 5.4, valign: 'top', fit: 'shrink' });
    }
  }

  // KPI scorecard
  const kpis = (view ? view.kpis : spec.kpis).slice(0, 8);
  if (kpis.length && spec.mode !== 'single_chart') {
    const s = slide('KPI');
    const width = 2.85;
    kpis.forEach((kpi, i) => {
      const x = 0.6 + (i % 4) * (width + 0.25);
      const y = 1.5 + Math.floor(i / 4) * 2.6;
      s.addShape(pres.ShapeType.roundRect, { x, y, w: width, h: 2.3, rectRadius: 0.1, fill: { color: COLORS.card }, line: { color: COLORS.border, width: 1 } });
      s.addText(kpi.title.toUpperCase(), { x: x + 0.15, y: y + 0.15, w: width - 0.3, h: 0.4, fontSize: 9, bold: true, color: COLORS.muted, fit: 'shrink' });
      s.addText(kpi.value, { x: x + 0.15, y: y + 0.6, w: width - 0.3, h: 0.8, fontSize: kpi.type === 'text' ? 13 : 22, bold: true, color: COLORS.text, fit: 'shrink' });
      const delta = kpi.delta;
      if (delta && delta.pct !== null) {
        const sign = delta.pct >= 0 ? '+' : '-';
        s.addText(`${sign}${Math.abs(delta.pct * 100).toFixed(1)}% ${delta.label}`, {
          x: x + 0.15, y: y + 1.5, w: width - 0.3, h: 0.4, fontSize: 9, bold: true, color: delta.direction === 'down' ? COLORS.red : COLORS.green,
        });
      } else if (kpi.subtitle && kpi.type !== 'text') {
        s.addText(kpi.subtitle, { x: x + 0.15, y: y + 1.5, w: width - 0.3, h: 0.4, fontSize: 9, color: COLORS.muted, fit: 'shrink' });
      }
    });
  }

  // One slide per chart (native chart when the type maps to one, otherwise the numbers as a table)
  const charts = (view ? view.charts : spec.charts).filter((c): c is ChartItem => Boolean(c));
  charts.forEach((chart) => {
    const s = slide(chart.title, [chart.subtitle, view ? '' : chart.insight].filter(Boolean).join('  ·  '));
    const points = chart.data.slice(0, MAX_POINTS);
    const labels = points.map((p) => String(p.name ?? p.x ?? ''));
    const values = points.map((p) => Number(p.value ?? p.y) || 0);
    const isDonut = chart.type === 'donut';
    if (NATIVE_TYPES.has(chart.type) && points.length) {
      const type = isDonut || chart.type === 'treemap' ? pres.ChartType.doughnut : chart.type === 'line' || chart.type === 'area' ? pres.ChartType.line : pres.ChartType.bar;
      s.addChart(type, [{ name: chart.title, labels, values }], {
        x: 0.6, y: 1.6, w: 7.6, h: 5.2, showTitle: false, showLegend: isDonut, legendColor: COLORS.muted,
        chartColors: isDonut || chart.type === 'treemap' ? COLORS.series : [COLORS.blue],
        catAxisLabelColor: COLORS.muted, valAxisLabelColor: COLORS.muted, barDir: chart.type === 'horizontal_bar' ? 'bar' : 'col',
      });
    }
    if (points.length) {
      const header = [t('showing'), chart.aggregation].map((text) => ({ text, options: { bold: true, color: COLORS.text, fill: { color: '1E293B' } } }));
      const body = points.slice(0, 10).map((p, i) => [
        { text: labels[i], options: { color: COLORS.muted } },
        { text: formatValue(p.value ?? p.y, chart, true), options: { color: COLORS.text, bold: true } },
      ]);
      s.addTable([header, ...body], {
        x: NATIVE_TYPES.has(chart.type) ? 8.5 : 0.6, y: 1.6, w: NATIVE_TYPES.has(chart.type) ? 4.2 : 12.1, fontSize: 9.5,
        fill: { color: COLORS.card }, border: { type: 'solid', pt: 0.5, color: COLORS.border },
      });
    }
  });

  await pres.writeFile({ fileName: `${safeName(spec.fileName || spec.title)}.pptx` });
}
