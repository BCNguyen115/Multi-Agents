'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import type { ColDef } from 'ag-grid-community';
import {
  AlertTriangle,
  Calendar,
  ChevronDown,
  ChevronUp,
  Database,
  Download,
  FileDown,
  Filter,
  Hash,
  Layers,
  LayoutDashboard,
  Lightbulb,
  Maximize2,
  Minimize2,
  Minus,
  Presentation,
  Printer,
  RotateCcw,
  Search,
  ShieldCheck,
  Table as TableIcon,
  TrendingDown,
  TrendingUp,
  X,
} from 'lucide-react';
import { EChartComponent } from './EChartComponent';
import type { ChartItem, DashboardSpec, FilteredDashboard, KPIItem } from '../../lib/types';
import { useIsDark } from '../../lib/useIsDark';
import { ui } from '../../lib/uiText';
import { ActiveFilters, filterDashboard, isDashboardSpecV2, toggleFilter } from '../../lib/dashboardApi';
import { isFilterableChart } from '../../lib/chartOption';
import { exportDashboardToPDF, exportDashboardToPPTX } from '../../lib/exportEngine';
import { toast } from '../../lib/toast';

interface DynamicDashboardProps {
  spec: DashboardSpec;
}

type Translate = (key: Parameters<typeof ui>[1], params?: Record<string, string | number>) => string;

// Static class names so Tailwind can see them (a chart's col_span comes from the server's 12-column layout)
const SPAN: Record<number, string> = {
  3: 'lg:col-span-3',
  4: 'lg:col-span-4',
  5: 'lg:col-span-5',
  6: 'lg:col-span-6',
  7: 'lg:col-span-7',
  8: 'lg:col-span-8',
  9: 'lg:col-span-9',
  12: 'lg:col-span-12',
};
const OTHER_LABELS = new Set(['Other', 'Khác']);
const KPI_ICONS: Record<string, React.ComponentType<{ className?: string }>> = { Database, TrendingUp, Layers, Calendar, Hash };
const FILTER_DEBOUNCE_MS = 250;
const SLICER_CHIP_LIMIT = 8; // chips shown before "+N more"
const SLICER_SEARCH_FROM = 12; // a slicer with more values than this gets a search box

const pct = (fraction: number) => `${fraction >= 0 ? '+' : '-'}${Math.abs(fraction * 100).toFixed(1)}%`;

function KpiCard({ kpi }: { kpi: KPIItem }) {
  const Icon = (kpi.icon && KPI_ICONS[kpi.icon]) || Hash;
  const delta = kpi.delta;
  const DeltaIcon = delta?.direction === 'up' ? TrendingUp : delta?.direction === 'down' ? TrendingDown : Minus;
  // Direction is told by the arrow and the sign: a fall in revenue is a fact, not an error state.
  return (
    <div data-testid={`kpi-${kpi.id}`} className="bg-surface p-4 rounded-xl border border-border flex flex-col justify-between gap-2 min-w-0">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold text-foreground-secondary uppercase tracking-wider truncate" title={kpi.title}>
          {kpi.title}
        </span>
        <Icon className="w-4 h-4 text-foreground-muted shrink-0" />
      </div>
      <p className={`font-bold font-mono tabular-nums text-foreground tracking-tight truncate ${kpi.type === 'text' ? 'text-base' : 'text-2xl'}`} title={kpi.value}>
        {kpi.value}
      </p>
      <div className="flex items-center justify-between gap-2 min-h-[1.5rem]">
        {delta && delta.pct !== null ? (
          <span className="inline-flex items-center gap-1 text-xs font-mono font-medium px-2 py-0.5 rounded-full border bg-surface-raised text-foreground border-border">
            <DeltaIcon className="w-3 h-3" aria-hidden="true" />
            <span className="tabular-nums">{pct(delta.pct)}</span>
            <span className="text-foreground-muted">{delta.label}</span>
          </span>
        ) : (
          <span />
        )}
        {kpi.subtitle && kpi.type !== 'text' && (
          <span className="text-xs text-foreground-muted truncate font-mono tabular-nums" title={kpi.subtitle}>
            {kpi.subtitle}
          </span>
        )}
      </div>
    </div>
  );
}

/** One filterable column: at most SLICER_CHIP_LIMIT chips (selected ones always shown), a search box for long lists. */
function SlicerRow({
  slicer,
  selected,
  onToggle,
  t,
}: {
  slicer: DashboardSpec['slicers'][number];
  selected: string[];
  onToggle: (field: string, value: string) => void;
  t: Translate;
}) {
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState(false);
  const needle = query.trim().toLowerCase();
  const matching = needle ? slicer.values.filter((v) => v.toLowerCase().includes(needle)) : slicer.values;
  const showAll = expanded || Boolean(needle);
  const visible = matching.filter((v, i) => showAll || i < SLICER_CHIP_LIMIT || selected.includes(v));
  const hidden = matching.length - visible.length;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs font-semibold text-foreground-secondary mr-1 max-w-[10rem] truncate" title={slicer.label}>
        {slicer.label}:
      </span>
      {slicer.values.length > SLICER_SEARCH_FROM && (
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('searchValues')}
          aria-label={`${slicer.label}: ${t('searchValues')}`}
          className="w-36 px-2.5 py-1 rounded-full text-xs bg-surface border border-border text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-accent-primary/40"
        />
      )}
      {visible.map((value) => {
        const on = selected.includes(value);
        return (
          <button
            key={value}
            type="button"
            aria-pressed={on}
            onClick={() => onToggle(slicer.field, value)}
            className={`px-2.5 py-1 rounded-full text-xs border transition-colors cursor-pointer max-w-[12rem] truncate focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40 ${
              on ? 'bg-accent-primary text-white border-accent-primary' : 'bg-surface-raised text-foreground-secondary border-border hover:border-border-strong'
            }`}
            title={value}
          >
            {value}
            {on && <X className="inline w-3 h-3 ml-1" aria-hidden="true" />}
          </button>
        );
      })}
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="px-2.5 py-1 rounded-full text-xs font-semibold text-accent-primary cursor-pointer hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
        >
          {t('showMore', { n: hidden })}
        </button>
      )}
      {expanded && !needle && matching.length > SLICER_CHIP_LIMIT && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="px-2.5 py-1 rounded-full text-xs font-semibold text-foreground-secondary cursor-pointer hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
        >
          {t('showLess')}
        </button>
      )}
    </div>
  );
}

const DashboardView: React.FC<DynamicDashboardProps> = ({ spec }) => {
  const isDark = useIsDark();
  const t: Translate = useCallback((key, params) => ui(spec.language, key, params), [spec.language]);

  const [filters, setFilters] = useState<ActiveFilters>({});
  const [view, setView] = useState<FilteredDashboard | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0); // bumped by "try again" so the same filters are sent once more
  const [fullscreen, setFullscreen] = useState(false);
  const [tableOpen, setTableOpen] = useState(true);
  const [quickFilter, setQuickFilter] = useState('');
  const gridRef = useRef<AgGridReact>(null);

  // A new dashboard starts unfiltered
  useEffect(() => {
    setFilters({});
    setView(null);
    setError(null);
  }, [spec]);

  // Server-side recompute (same compiler + verifier as the original dashboard), debounced, latest request wins
  const active = Object.keys(filters).length > 0;
  useEffect(() => {
    if (!active) {
      setView(null);
      setError(null);
      setBusy(false);
      return undefined;
    }
    const controller = new AbortController();
    setBusy(true);
    const timer = setTimeout(() => {
      filterDashboard(spec, filters, controller.signal)
        .then((result) => {
          setView(result);
          setError(null);
        })
        .catch((err: unknown) => {
          if (controller.signal.aborted) return;
          setError(err instanceof Error ? err.message : t('filterError'));
        })
        .finally(() => {
          if (!controller.signal.aborted) setBusy(false);
        });
    }, FILTER_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [filters, active, spec, t, attempt]);

  const kpis = view?.kpis ?? spec.kpis;
  const charts: (ChartItem | null)[] = useMemo(() => (view ? view.charts : spec.charts), [view, spec.charts]);
  const noRows = Boolean(view && view.rows_used === 0);

  const rows = useMemo(() => {
    const entries = Object.entries(filters);
    if (!entries.length) return spec.table.rows;
    return spec.table.rows.filter((row) => entries.every(([field, values]) => values.includes(String(row[field] ?? ''))));
  }, [filters, spec.table.rows]);

  const columnDefs = useMemo<ColDef[]>(
    () =>
      spec.table.columns.map((column) => ({
        field: column.field,
        headerName: column.headerName,
        sortable: true,
        resizable: true,
        filter: column.type === 'number' ? 'agNumberColumnFilter' : 'agTextColumnFilter',
        type: column.type === 'number' ? 'numericColumn' : undefined,
        valueFormatter:
          column.type === 'number'
            ? (p: { value: unknown }) => (typeof p.value === 'number' ? p.value.toLocaleString('en-US', { maximumFractionDigits: 4 }) : '')
            : undefined,
      })),
    [spec.table.columns]
  );

  const selectFromChart = useCallback((chart: ChartItem, name: string) => {
    const field = chart.spec.dimension;
    if (!field || OTHER_LABELS.has(name)) return;
    setFilters((prev) => toggleFilter(prev, field, name));
  }, []);

  const toggleSlicer = useCallback((field: string, value: string) => setFilters((prev) => toggleFilter(prev, field, value)), []);

  const runExport = async (kind: 'pptx' | 'pdf') => {
    try {
      toast.info(t('exporting'));
      if (kind === 'pdf') exportDashboardToPDF();
      else {
        await exportDashboardToPPTX(spec, view);
        toast.success(t('exported'));
      }
    } catch (err) {
      toast.error(`${t('exportFailed')}: ${err instanceof Error ? err.message : ''}`);
    }
  };

  const { analysis, story } = spec;
  const single = spec.mode === 'single_chart';
  const shownRows = view ? view.rows_used : analysis.rows_used;
  const hasStoryDetails = Boolean(story && (story.sections.length > 0 || story.actions.length > 0 || story.caveats.length > 0 || story.next_questions.length > 0));
  const unverified = spec.verified === false || Boolean(view && !view.verified);

  return (
    <div
      data-testid="dashboard-container"
      className={`dynamic-dashboard-container ${
        fullscreen ? 'fixed inset-0 md:left-[var(--sidebar-width,4rem)] z-40 overflow-y-auto bg-surface p-4 sm:p-6 space-y-5' : 'w-full space-y-5 my-4 bg-surface p-4 sm:p-5 rounded-2xl border border-border'
      }`}
    >
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 border-b border-border pb-4">
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2.5 bg-accent-primary text-white rounded-xl shrink-0">
            <LayoutDashboard className="w-5 h-5" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg sm:text-xl font-extrabold text-foreground tracking-tight truncate" title={spec.title}>
              {spec.title}
            </h2>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-xs text-foreground-secondary font-mono tabular-nums">
              <span>
                {shownRows.toLocaleString('en-US')} {t('of')} {analysis.rows_total.toLocaleString('en-US')} {t('rows')} · {spec.table.columns.length} {t('columns')}
              </span>
              {analysis.sampled && (
                <span className="inline-flex items-center gap-1 text-foreground-secondary">
                  <AlertTriangle className="w-3.5 h-3.5" aria-hidden="true" />
                  {t('sampled', { used: analysis.rows_used.toLocaleString('en-US'), total: analysis.rows_total.toLocaleString('en-US') })}
                </span>
              )}
              {unverified ? (
                <span role="status" className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-accent-error/30 bg-accent-error/10 text-accent-error font-sans font-semibold">
                  <AlertTriangle className="w-3.5 h-3.5" aria-hidden="true" /> {t('unverified')}
                </span>
              ) : (
                <span role="status" className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-accent-verifier/30 bg-accent-verifier/10 text-accent-verifier font-sans font-semibold">
                  <ShieldCheck className="w-3.5 h-3.5" aria-hidden="true" /> {t('verified')}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <details className="relative">
            <summary className="btn-dash list-none [&::-webkit-details-marker]:hidden">
              <FileDown className="w-3.5 h-3.5 text-accent-primary" aria-hidden="true" /> {t('export')}
              <ChevronDown className="w-3.5 h-3.5 text-foreground-muted" aria-hidden="true" />
            </summary>
            <div className="absolute right-0 mt-1 z-20 min-w-[9rem] rounded-xl border border-border-strong bg-surface p-1 flex flex-col">
              {(['pdf', 'pptx'] as const).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  onClick={(e) => {
                    e.currentTarget.closest('details')?.removeAttribute('open');
                    runExport(kind);
                  }}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold text-foreground hover:bg-surface-raised cursor-pointer text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
                >
                  {kind === 'pdf' ? <FileDown className="w-3.5 h-3.5 text-accent-primary" aria-hidden="true" /> : <Presentation className="w-3.5 h-3.5 text-accent-primary" aria-hidden="true" />}
                  {kind === 'pdf' ? t('exportPdf') : t('exportPptx')}
                </button>
              ))}
            </div>
          </details>
          <button type="button" onClick={() => setFullscreen((v) => !v)} className="btn-dash" title={fullscreen ? t('exitFullscreen') : t('fullscreen')}>
            {fullscreen ? <Minimize2 className="w-3.5 h-3.5" aria-hidden="true" /> : <Maximize2 className="w-3.5 h-3.5" aria-hidden="true" />}
            <span className="hidden sm:inline">{fullscreen ? t('exitFullscreen') : t('fullscreen')}</span>
          </button>
        </div>
      </div>

      {/* KPIs first: the numbers are what the data specialist came for */}
      {!single && kpis.length > 0 && !noRows && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {kpis.map((kpi) => (
            <KpiCard key={kpi.id} kpi={kpi} />
          ))}
        </div>
      )}

      {/* Story: the headline always, the rest on demand */}
      {!single && story && (
        <section className="rounded-xl border border-border p-4 space-y-2" data-testid="story-panel">
          <h3 className="sr-only">{t('story')}</h3>
          <p className="flex items-start gap-2 text-base font-semibold text-foreground leading-snug">
            <Lightbulb className="w-4 h-4 mt-1 shrink-0 text-accent-primary" aria-hidden="true" />
            <span>{story.headline}</span>
          </p>
          {active && <p className="text-xs text-foreground-muted italic">{t('filteredNote')}</p>}
          {hasStoryDetails && (
            <details className="group">
              <summary className="inline-flex items-center gap-1 cursor-pointer rounded text-xs font-semibold text-accent-primary hover:underline list-none [&::-webkit-details-marker]:hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40">
                {t('details')} <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180" aria-hidden="true" />
              </summary>
              <div className="mt-3 space-y-3">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {story.sections.map((section) => (
                    <div key={section.key} className="bg-surface-raised/50 rounded-xl border border-border p-3">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-foreground-secondary mb-1.5">{section.title}</h4>
                      <ul className="space-y-1.5 text-xs leading-relaxed text-foreground-secondary list-disc pl-4">
                        {section.items.map((item) => (
                          <li key={item.id}>{item.text}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
                {(story.actions.length > 0 || story.caveats.length > 0) && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {story.actions.length > 0 && (
                      <div className="rounded-xl border border-accent-primary/30 bg-accent-primary/5 p-3">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-accent-primary mb-1.5">{t('actions')}</h4>
                        <ul className="space-y-1.5 text-xs leading-relaxed text-foreground-secondary list-disc pl-4">
                          {story.actions.map((action, i) => (
                            <li key={i}>{action.text}</li>
                          ))}
                        </ul>
                        {story.hypothesis_note && <p className="mt-2 text-xs italic text-foreground-muted">{story.hypothesis_note}</p>}
                      </div>
                    )}
                    {story.caveats.length > 0 && (
                      <div className="rounded-xl border border-border-strong bg-surface-raised/50 p-3">
                        <h4 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-foreground mb-1.5">
                          <AlertTriangle className="w-3.5 h-3.5" aria-hidden="true" /> {t('watch')}
                        </h4>
                        <ul className="space-y-1.5 text-xs leading-relaxed text-foreground-secondary list-disc pl-4">
                          {story.caveats.map((caveat, i) => (
                            <li key={i}>{caveat.text}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
                {story.next_questions.length > 0 && (
                  <div className="text-xs text-foreground-secondary">
                    <span className="font-bold uppercase tracking-wider text-xs text-foreground-muted">{t('questions')}: </span>
                    {story.next_questions.join(' · ')}
                  </div>
                )}
              </div>
            </details>
          )}
        </section>
      )}

      {/* Slicers */}
      {!single && spec.slicers.length > 0 && (
        <section className="bg-surface border border-border rounded-xl p-4 space-y-3" data-testid="slicers">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-bold text-foreground uppercase tracking-wider">
              <Filter className="w-4 h-4 text-accent-primary" aria-hidden="true" /> {t('filters')}
              {busy && <span role="status" className="text-xs font-normal normal-case text-foreground-muted">{t('filtering')}</span>}
            </div>
            {active && (
              <button type="button" onClick={() => setFilters({})} className="text-xs font-semibold text-foreground inline-flex items-center gap-1 cursor-pointer rounded hover:text-accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40">
                <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" /> {t('clear')}
              </button>
            )}
          </div>
          <div className="space-y-2">
            {spec.slicers.map((slicer) => (
              <SlicerRow key={slicer.field} slicer={slicer} selected={filters[slicer.field] ?? []} onToggle={toggleSlicer} t={t} />
            ))}
          </div>
          {error && (
            <p className="flex flex-wrap items-center gap-2 text-xs text-accent-error" role="alert">
              <span>
                {t('filterError')}: {error}
              </span>
              <button type="button" onClick={() => setAttempt((n) => n + 1)} className="font-semibold underline cursor-pointer rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40">
                {t('retry')}
              </button>
            </p>
          )}
        </section>
      )}

      {/* Charts */}
      {noRows ? (
        <div className="py-16 text-center text-sm text-foreground-muted" role="status">
          {t('noRows')}
        </div>
      ) : (
        <div className={`grid grid-cols-12 gap-4 ${busy ? 'opacity-60 transition-opacity' : ''}`}>
          {spec.charts.map((original, index) => {
            const chart = charts[index];
            const span = single ? 12 : original.col_span;
            const field = original.spec.dimension;
            const selected = field && filters[field]?.length === 1 ? filters[field][0] : null;
            return (
              <div
                key={original.id}
                className={`col-span-12 ${SPAN[span] ?? 'lg:col-span-6'} bg-surface p-4 rounded-xl border border-border flex flex-col min-w-0`}
              >
                <div className="border-b border-border pb-2 mb-3">
                  <h3 className="font-bold text-foreground text-sm truncate" title={(chart ?? original).title}>
                    {(chart ?? original).title}
                  </h3>
                  {chart?.subtitle && <p className="text-xs text-foreground-muted mt-0.5">{chart.subtitle}</p>}
                  {!view && original.insight && <p className="text-xs text-foreground-secondary mt-1.5 leading-relaxed">{original.insight}</p>}
                </div>
                {chart ? (
                  <EChartComponent chart={chart} selected={selected} height={single ? '440px' : '300px'} onSelect={(name) => selectFromChart(chart, name)} />
                ) : (
                  <div className="h-[300px] flex items-center justify-center text-xs text-foreground-muted italic text-center px-4">{t('noData')}</div>
                )}
                {!single && isFilterableChart(original) && <p className="text-xs text-foreground-muted mt-2">{t('filterHint')}</p>}
              </div>
            );
          })}
        </div>
      )}

      {/* Data table */}
      <section className="bg-surface rounded-xl border border-border overflow-hidden">
        <div className="p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border bg-surface-raised/40">
          <div className="flex items-center gap-2.5 min-w-0">
            <TableIcon className="w-4 h-4 text-accent-primary shrink-0" aria-hidden="true" />
            <span className="font-bold text-foreground text-sm truncate">{spec.table.title}</span>
            <span className="px-2 py-0.5 bg-accent-primary/10 text-accent-primary border border-accent-primary/20 rounded-full text-xs font-semibold font-mono tabular-nums shrink-0">
              {rows.length.toLocaleString('en-US')} / {spec.table.totalRows.toLocaleString('en-US')}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-foreground-muted absolute left-2.5 top-2.5" aria-hidden="true" />
              <input
                type="text"
                placeholder={t('quickSearch')}
                aria-label={t('quickSearch')}
                value={quickFilter}
                onChange={(e) => setQuickFilter(e.target.value)}
                className="pl-8 pr-3 py-1.5 bg-surface border border-border rounded-lg text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-accent-primary w-36 sm:w-44"
              />
            </div>
            <button type="button" className="btn-dash" onClick={() => gridRef.current?.api.exportDataAsCsv({ fileName: `${spec.fileName.replace(/\.[^/.]+$/, '')}.csv` })}>
              <Download className="w-3.5 h-3.5 text-accent-primary" aria-hidden="true" /> {t('exportCsv')}
            </button>
            <button type="button" className="btn-dash" onClick={() => window.print()}>
              <Printer className="w-3.5 h-3.5 text-foreground-muted" aria-hidden="true" /> {t('print')}
            </button>
            <button type="button" className="btn-dash" onClick={() => setTableOpen((v) => !v)} aria-expanded={tableOpen}>
              {tableOpen ? <ChevronUp className="w-3.5 h-3.5" aria-hidden="true" /> : <ChevronDown className="w-3.5 h-3.5" aria-hidden="true" />}
              <span>{tableOpen ? t('collapse') : t('expand')}</span>
            </button>
          </div>
        </div>
        {tableOpen && (
          <div className="p-3">
            {spec.table.truncated && <p className="text-xs text-foreground-muted mb-2">{t('tableNote', { n: spec.table.rows.length.toLocaleString('en-US') })}</p>}
            <div className={`ag-theme-alpine ${isDark ? 'ag-theme-quartz-dark ag-theme-alpine-dark' : 'ag-theme-quartz'} w-full h-[320px] rounded-xl border border-border overflow-hidden`}>
              <AgGridReact
                ref={gridRef}
                rowData={rows}
                columnDefs={columnDefs}
                pagination
                paginationPageSize={20}
                paginationPageSizeSelector={[10, 20, 50, 100]}
                quickFilterText={quickFilter}
              />
            </div>
          </div>
        )}
      </section>
    </div>
  );
};

/** Renders a spec v2; a dashboard saved by an older version (no `analysis`, `story`...) gets a notice instead of crashing. */
export const DynamicDashboard: React.FC<DynamicDashboardProps> = ({ spec }) =>
  isDashboardSpecV2(spec) ? (
    <DashboardView spec={spec} />
  ) : (
    <div data-testid="dashboard-outdated" role="status" className="my-4 flex items-start gap-3 rounded-2xl border border-border-strong bg-surface-raised p-4 text-sm text-foreground-secondary">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-foreground" aria-hidden="true" />
      <span>
        Dashboard này được tạo bởi phiên bản cũ nên không còn hiển thị được. Hãy tải lại tệp dữ liệu và yêu cầu dựng dashboard mới. / This dashboard was
        created by an older version and can no longer be displayed. Upload the file again to rebuild it.
      </span>
    </div>
  );
