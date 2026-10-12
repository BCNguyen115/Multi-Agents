'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import type { ColDef, IDatasource, IGetRowsParams } from 'ag-grid-community';
import { ChevronDown, ChevronUp, Download, Printer, Search, Table as TableIcon } from 'lucide-react';
import type { DashboardSpec } from '../../lib/types';
import type { ui } from '../../lib/uiText';
import { ActiveFilters, TableError, downloadTableCsv, fetchTableRows } from '../../lib/dashboardApi';
import { toast } from '../../lib/toast';

type Translate = (key: Parameters<typeof ui>[1], params?: Record<string, string | number>) => string;

const SEARCH_DEBOUNCE_MS = 300;
const PAGE_SIZES = [10, 20, 50, 100];

interface Props {
  spec: DashboardSpec;
  /** The slicers picked above the charts: the table follows them. */
  filters: ActiveFilters;
  isDark: boolean;
  t: Translate;
}

/**
 * The data table of a dashboard: EVERY row of the uploaded file. The grid asks the server for the page it shows
 * (search, column filters, slicers and sorting run there over all rows, so any single row can be found), and "CSV" exports
 * every matching row. The browser holds only a preview of the table (`spec.table.rows`); if the server cannot page it (the
 * session's file expired) the grid falls back to that preview and says so.
 */
export function DashboardTable({ spec, filters, isDark, t }: Props) {
  const [open, setOpen] = useState(true);
  const [quickFilter, setQuickFilter] = useState('');
  const [search, setSearch] = useState('');
  const [offline, setOffline] = useState(!spec.sessionId); // true: show the preview rows held in the spec
  const [matched, setMatched] = useState<number | null>(null); // rows matching the search / filters, from the server
  const [exporting, setExporting] = useState(false);
  const gridRef = useRef<AgGridReact>(null);

  // A new dashboard asks the server again
  useEffect(() => {
    setOffline(!spec.sessionId);
    setMatched(null);
    setQuickFilter('');
    setSearch('');
  }, [spec]);

  useEffect(() => {
    const timer = setTimeout(() => setSearch(quickFilter.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [quickFilter]);

  // Preview mode: the slicers filter the rows held here
  const previewRows = useMemo(() => {
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

  // A new datasource (new search or slicers) makes the grid reload from the first page
  const datasource = useMemo<IDatasource>(
    () => ({
      getRows: (params: IGetRowsParams) => {
        const sort = params.sortModel.map((item) => ({ field: item.colId, dir: item.sort }));
        fetchTableRows(spec, { search, slicers: filters, sort, columnFilters: params.filterModel }, params.startRow, params.endRow - params.startRow)
          .then((page) => {
            params.successCallback(page.rows, page.total);
            setMatched(page.total);
          })
          .catch((error: unknown) => {
            params.failCallback();
            if (error instanceof TableError && error.status === 422) toast.error(error.message);
            else setOffline(true); // the file is no longer on the server (or it cannot be reached): show the preview
          });
      },
    }),
    [spec, search, filters]
  );

  const exportCsv = async () => {
    const fileName = `${spec.fileName.replace(/\.[^/.]+$/, '')}.csv`;
    const api = gridRef.current?.api;
    if (!api) return;
    if (offline) {
      api.exportDataAsCsv({ fileName });
      return;
    }
    setExporting(true);
    try {
      const sort = api
        .getColumnState()
        .filter((column) => column.sort)
        .sort((a, b) => (a.sortIndex ?? 0) - (b.sortIndex ?? 0))
        .map((column) => ({ field: column.colId, dir: column.sort as 'asc' | 'desc' }));
      const blob = await downloadTableCsv(spec, { search, slicers: filters, sort, columnFilters: api.getFilterModel() });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = fileName;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(error instanceof Error && error.message ? error.message : t('exportFailed'));
    } finally {
      setExporting(false);
    }
  };

  const shown = offline ? previewRows.length : (matched ?? spec.table.totalRows);
  const gridClass = `${isDark ? 'ag-theme-quartz-dark' : 'ag-theme-quartz'} w-full h-[320px] rounded-xl border border-border overflow-hidden`;

  return (
    <section className="bg-surface rounded-xl border border-border overflow-hidden">
      <div className="p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border bg-surface-raised/40">
        <div className="flex items-center gap-2.5 min-w-0">
          <TableIcon className="w-4 h-4 text-accent-primary shrink-0" aria-hidden="true" />
          <span className="font-bold text-foreground text-sm truncate">{spec.table.title}</span>
          <span
            data-testid="table-count"
            className="px-2 py-0.5 bg-accent-primary/10 text-accent-primary border border-accent-primary/20 rounded-full text-xs font-semibold font-mono tabular-nums shrink-0"
          >
            {shown.toLocaleString('en-US')} / {spec.table.totalRows.toLocaleString('en-US')}
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
          <button type="button" className="btn-dash" onClick={exportCsv} disabled={exporting} aria-busy={exporting}>
            <Download className="w-3.5 h-3.5 text-accent-primary" aria-hidden="true" /> {t('exportCsv')}
          </button>
          <button type="button" className="btn-dash" onClick={() => window.print()}>
            <Printer className="w-3.5 h-3.5 text-foreground-muted" aria-hidden="true" /> {t('print')}
          </button>
          <button type="button" className="btn-dash" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? <ChevronUp className="w-3.5 h-3.5" aria-hidden="true" /> : <ChevronDown className="w-3.5 h-3.5" aria-hidden="true" />}
            <span>{open ? t('collapse') : t('expand')}</span>
          </button>
        </div>
      </div>
      {open && (
        <div className="p-3">
          {offline && spec.sessionId && (
            <p role="status" className="text-xs text-foreground-secondary mb-2">
              {t('tableOffline')}
            </p>
          )}
          {offline && spec.table.truncated && (
            <p className="text-xs text-foreground-muted mb-2">
              {t('tableNote', { n: spec.table.rows.length.toLocaleString('en-US'), total: spec.table.totalRows.toLocaleString('en-US') })}
            </p>
          )}
          <div className={gridClass}>
            {offline ? (
              <AgGridReact
                key="preview"
                ref={gridRef}
                rowData={previewRows}
                columnDefs={columnDefs}
                pagination
                paginationPageSize={20}
                paginationPageSizeSelector={PAGE_SIZES}
                quickFilterText={quickFilter}
              />
            ) : (
              <AgGridReact
                key="server"
                ref={gridRef}
                rowModelType="infinite"
                datasource={datasource}
                cacheBlockSize={100}
                maxBlocksInCache={20}
                columnDefs={columnDefs}
                pagination
                paginationPageSize={20}
                paginationPageSizeSelector={PAGE_SIZES}
              />
            )}
          </div>
        </div>
      )}
    </section>
  );
}
