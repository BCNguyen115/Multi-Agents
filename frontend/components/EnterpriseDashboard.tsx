'use client';

import React, { useState, useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ColDef, GridOptions } from 'ag-grid-community';
import ReactECharts from 'echarts-for-react';
import { CSVMetadata } from '../lib/types';
import { Filter, BarChart3, Table as TableIcon, Layers, Hash } from 'lucide-react';
import { useIsDark } from '../lib/useIsDark';
import { t, useLang } from '../lib/i18n';
import { readTheme } from './dashboard/EChartComponent';

interface EnterpriseDashboardProps {
  metadata: CSVMetadata;
  generatedCode?: string;
}

export const EnterpriseDashboard: React.FC<EnterpriseDashboardProps> = ({ metadata }) => {
  const isDark = useIsDark();
  const [lang] = useLang();
  const [selectedFilters, setSelectedFilters] = useState<Record<string, string[]>>({});

  const filteredData = useMemo(() => {
    if (!metadata.sampleData || metadata.sampleData.length === 0) return [];
    return metadata.sampleData.filter((row) => {
      for (const [col, selectedVals] of Object.entries(selectedFilters)) {
        if (selectedVals.length > 0 && !selectedVals.includes(String(row[col]))) {
          return false;
        }
      }
      return true;
    });
  }, [metadata.sampleData, selectedFilters]);

  const isIdColumn = (colName: string) => {
    const k = colName.toLowerCase();
    return (
      k === 'id' || k.includes('id_') || k.endsWith('_id') ||
      k.includes('code') || k.includes('zip') || k.includes('phone') ||
      k.includes('index') || k.includes('ssn') || k.endsWith('_num') || k.endsWith('number')
    );
  };

  const totalRowsCount = metadata.totalRows;
  const cleanNumericCols = useMemo(() => {
    return metadata.numericCols.filter((col) => !isIdColumn(col));
  }, [metadata.numericCols]);

  const primaryNumericCol = cleanNumericCols[0] || '';
  const secondaryNumericCol = cleanNumericCols[1] || '';

  const primarySum = useMemo(() => {
    if (filteredData.length === metadata.sampleData.length && metadata.summary[primaryNumericCol]?.sum) {
      return metadata.summary[primaryNumericCol].sum!;
    }
    return filteredData.reduce((acc, curr) => acc + (Number(curr[primaryNumericCol]) || 0), 0);
  }, [primaryNumericCol, metadata.summary, filteredData, metadata.sampleData.length]);

  const primaryAvg = useMemo(() => {
    if (filteredData.length === metadata.sampleData.length && metadata.summary[primaryNumericCol]?.avg) {
      return metadata.summary[primaryNumericCol].avg!;
    }
    return filteredData.length ? primarySum / filteredData.length : 0;
  }, [primaryNumericCol, primarySum, filteredData.length, metadata.summary, metadata.sampleData.length]);

  const columnDefs: ColDef[] = useMemo(() => {
    return metadata.columns.map((col) => ({
      field: col.name,
      headerName: col.name.replace(/_/g, ' ').toUpperCase(),
      sortable: true,
      filter: true,
      resizable: true,
      enableRowGroup: true,
    }));
  }, [metadata.columns]);

  const gridOptions: GridOptions = {
    pagination: true,
    paginationPageSize: 10,
    domLayout: 'normal',
  };

  const primaryCatCol = metadata.categoricalCols[0] || metadata.columns[0]?.name || '';
  const chartData = useMemo(() => {
    if (!primaryCatCol) return [];
    const agg: Record<string, number> = {};
    filteredData.forEach((row) => {
      const key = String(row[primaryCatCol] || 'Other');
      const val = primaryNumericCol ? Number(row[primaryNumericCol]) || 1 : 1;
      agg[key] = (agg[key] || 0) + val;
    });
    return Object.entries(agg).map(([name, value]) => ({ name, value }));
  }, [filteredData, primaryCatCol, primaryNumericCol]);

  // The same charting library as the dashboards of the data agent (ECharts), so the page ships one chart engine.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- isDark is the re-read trigger for the CSS variables
  const theme = useMemo(() => readTheme(isDark), [isDark]);
  const barOption = useMemo(
    () => ({
      textStyle: { fontFamily: theme.font },
      grid: { left: 44, right: 12, top: 12, bottom: 32 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: chartData.map((d) => d.name), axisLabel: { fontSize: 11, color: theme.text } },
      yAxis: { type: 'value', axisLabel: { fontSize: 11, color: theme.text }, splitLine: { lineStyle: { color: theme.grid, type: 'dashed' } } },
      series: [{ type: 'bar', data: chartData.map((d) => d.value), itemStyle: { color: theme.palette[0], borderRadius: [4, 4, 0, 0] } }],
    }),
    [chartData, theme],
  );
  const pieOption = useMemo(
    () => ({
      textStyle: { fontFamily: theme.font },
      color: theme.palette,
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, textStyle: { fontSize: 11, color: theme.text } },
      series: [{ type: 'pie', radius: ['35%', '62%'], center: ['50%', '45%'], padAngle: 2, label: { show: false }, data: chartData }],
    }),
    [chartData, theme],
  );

  return (
    <div data-testid="dashboard-container" className="space-y-6 my-4 bg-surface p-6 rounded-2xl border border-border shadow-xs">
      {/* Dashboard Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-border pb-4 gap-3">
        <div>
          <h2 className="text-xl font-bold text-foreground flex items-center gap-2">
            <Layers className="w-6 h-6 text-accent-primary" />
            {t(lang, 'ent.title')}
          </h2>
          <p className="text-xs text-foreground-muted mt-1">
            {t(lang, 'ent.poweredBy')} <span className="font-semibold text-foreground-secondary">DuckDB-Wasm</span> & ECharts / AG Grid
          </p>
        </div>

        <div className="flex items-center space-x-2 text-xs bg-surface-raised border border-border px-3 py-1.5 rounded-lg">
          <Hash className="w-4 h-4 text-accent-primary" />
          <span className="text-foreground-muted">{t(lang, 'ent.totalRowsLabel')}</span>
          <span className="font-bold text-foreground tabular-nums">{totalRowsCount.toLocaleString()}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Sidebar Slicers */}
        <div className="lg:col-span-1 bg-surface-raised p-4 rounded-xl border border-border space-y-4">
          <div className="flex items-center space-x-2 font-bold text-foreground text-sm border-b border-border pb-2">
            <Filter className="w-4 h-4 text-accent-primary" />
            <span>{t(lang, 'ent.filters')}</span>
          </div>

          {metadata.categoricalCols.length === 0 ? (
            <p className="text-xs text-foreground-muted italic">{t(lang, 'ent.noCategorical')}</p>
          ) : (
            metadata.categoricalCols.slice(0, 3).map((catCol) => {
              const uniqueVals = Array.from(
                new Set(metadata.sampleData.map((r) => String(r[catCol])).filter(Boolean))
              );

              return (
                <div key={catCol} className="space-y-1.5">
                  <label className="text-xs font-semibold text-foreground-secondary">
                    {catCol.replace(/_/g, ' ')}:
                  </label>
                  <select
                    multiple
                    value={selectedFilters[catCol] || []}
                    onChange={(e) => {
                      const options = Array.from(e.target.selectedOptions, (option) => option.value);
                      setSelectedFilters((prev) => ({ ...prev, [catCol]: options }));
                    }}
                    className="w-full text-xs border border-border rounded-lg p-2 bg-surface text-foreground focus:ring-2 focus:ring-accent-primary/30 focus:outline-none min-h-20"
                  >
                    {uniqueVals.map((val) => (
                      <option key={val} value={val}>{val}</option>
                    ))}
                  </select>
                  <p className="text-2xs font-mono text-foreground-muted">Hold Ctrl/Cmd for multi-select</p>
                </div>
              );
            })
          )}
        </div>

        <div className="lg:col-span-3 space-y-6">
          {/* KPI Cards: 112px, a 3px token-colored bar on the left (.kpi-card), figures in tabular mono */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="enterprise-card kpi-card h-[112px] min-h-[112px] pr-4 py-3.5 flex flex-col justify-between overflow-hidden">
              <p className="text-xs font-semibold text-foreground-muted uppercase tracking-wider truncate">{t(lang, 'ent.totalRecords')}</p>
              <p className="text-2xl font-bold font-mono tabular-nums text-foreground tracking-tight">{totalRowsCount.toLocaleString()}</p>
              <span className="text-xs text-foreground-muted font-mono truncate">{t(lang, 'ent.hintRows')}</span>
            </div>

            {primaryNumericCol && (
              <div className="enterprise-card kpi-card h-[112px] min-h-[112px] pr-4 py-3.5 flex flex-col justify-between overflow-hidden">
                <p className="text-xs font-semibold text-foreground-muted uppercase tracking-wider truncate" title={t(lang, 'ent.totalOf', { column: primaryNumericCol.replace(/_/g, ' ') })}>
                  {t(lang, 'ent.totalOf', { column: primaryNumericCol.replace(/_/g, ' ') })}
                </p>
                <p className="text-2xl font-bold font-mono tabular-nums text-foreground tracking-tight truncate">
                  {primarySum.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </p>
                <span className="text-xs text-foreground-muted font-mono truncate">{t(lang, 'ent.hintSum')}</span>
              </div>
            )}

            {primaryNumericCol && (
              <div className="enterprise-card kpi-card h-[112px] min-h-[112px] pr-4 py-3.5 flex flex-col justify-between overflow-hidden">
                <p className="text-xs font-semibold text-foreground-muted uppercase tracking-wider truncate" title={t(lang, 'ent.avgOf', { column: primaryNumericCol.replace(/_/g, ' ') })}>
                  {t(lang, 'ent.avgOf', { column: primaryNumericCol.replace(/_/g, ' ') })}
                </p>
                <p className="text-2xl font-bold font-mono tabular-nums text-foreground tracking-tight truncate">
                  {primaryAvg.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </p>
                <span className="text-xs text-foreground-muted font-mono truncate">{t(lang, 'ent.hintAvg')}</span>
              </div>
            )}
          </div>

          {/* Charts Grid */}
          <div className="enterprise-card p-5 space-y-4">
            <div className="flex items-center space-x-2 font-bold text-foreground text-sm border-b border-border pb-3">
              <BarChart3 className="w-4 h-4 text-accent-primary" />
              <span>{t(lang, 'ent.visual')}</span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="h-64">
                <p className="text-xs font-semibold text-foreground-secondary mb-2 text-center">
                  {t(lang, 'ent.distribution', { column: primaryCatCol.replace(/_/g, ' ') })}
                </p>
                <ReactECharts option={barOption} style={{ height: '100%', width: '100%' }} notMerge />

              </div>

              <div className="h-64">
                <p className="text-xs font-semibold text-foreground-secondary mb-2 text-center">
                  {t(lang, 'ent.proportion', { column: primaryCatCol.replace(/_/g, ' ') })}
                </p>
                <ReactECharts option={pieOption} style={{ height: '100%', width: '100%' }} notMerge />

              </div>
            </div>
          </div>
        </div>
      </div>

      {/* AG Grid Table */}
      <div className="enterprise-card p-5 space-y-3">
        <div className="flex items-center justify-between border-b border-border pb-3">
          <div className="flex items-center space-x-2 font-bold text-foreground text-sm">
            <TableIcon className="w-4 h-4 text-accent-primary" />
            <span>{t(lang, 'ent.dataTable')}</span>
          </div>
          <span className="text-xs text-foreground-muted font-mono tabular-nums">
            {filteredData.length.toLocaleString()} / {totalRowsCount.toLocaleString()}
          </span>
        </div>

        <div className={`${isDark ? 'ag-theme-quartz-dark' : 'ag-theme-quartz'} w-full h-80 rounded-lg overflow-hidden border border-border`}>
          <AgGridReact
            rowData={filteredData}
            columnDefs={columnDefs}
            gridOptions={gridOptions}
          />
        </div>

      </div>
    </div>
  );
};
