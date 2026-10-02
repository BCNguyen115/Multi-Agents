'use client';

import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Database, LayoutGrid, ChevronDown, ChevronUp, Sparkles, BarChart2, CheckCircle2 } from 'lucide-react';
import { ChatMessage } from '../lib/types';
import { t, useLang } from '../lib/i18n';

interface DataSummaryProps {
  totalRows?: number;
  totalCols?: number;
  columns?: string[];
  markdownContent: string;
  onGenerateDashboard?: () => void;
  message?: ChatMessage | Record<string, any>;
  metadata?: Record<string, any>;
}

const extractDataMetrics = (text: string) => {
  let rows: number | null = null;
  let cols: number | null = null;

  if (text) {
    let rowMatch = text.match(/(?:Số lượng dòng|Tổng số dòng|Số bản ghi)\D*?([0-9,.]+)/i);
    if (!rowMatch) rowMatch = text.match(/([0-9,.]+)\s*(?:dòng|bản ghi)/i);
    if (rowMatch && rowMatch[1]) {
      const cleaned = rowMatch[1].replace(/[,.]/g, '');
      if (cleaned) rows = parseInt(cleaned, 10);
    }

    let colMatch = text.match(/(?:Số lượng cột|Tổng số cột|Số trường|Số thuộc tính)\D*?([0-9,.]+)/i);
    if (!colMatch) colMatch = text.match(/([0-9,.]+)\s*(?:cột|trường|thuộc tính)/i);
    if (colMatch && colMatch[1]) {
      const cleaned = colMatch[1].replace(/[,.]/g, '');
      if (cleaned) cols = parseInt(cleaned, 10);
    }
  }

  return { rows, cols };
};

function parseMetricsFromMarkdown(content: string) {
  let extractedRows: number | undefined;
  let extractedCols: number | undefined;
  const extractedColumns: string[] = [];

  const rowMatch = content.match(/(?:Tổng số dòng|Số bản ghi|Số lượng dòng|\*\*Tổng số dòng\*\*)[^\n|]*[|:]\s*`?\*?\*?([\d,.]+)/i);
  if (rowMatch) {
    const parsed = parseInt(rowMatch[1].replace(/,/g, ''), 10);
    if (!isNaN(parsed)) extractedRows = parsed;
  }

  const colMatch = content.match(/(?:Tổng số cột|Số thuộc tính|Số lượng cột|\*\*Tổng số cột\*\*)[^\n|]*[|:]\s*`?\*?\*?([\d,.]+)/i);
  if (colMatch) {
    const parsed = parseInt(colMatch[1].replace(/,/g, ''), 10);
    if (!isNaN(parsed)) extractedCols = parsed;
  }

  const colBadgeRegex = /[-*]\s*`([^`]+)`/g;
  let m;
  while ((m = colBadgeRegex.exec(content)) !== null) {
    if (m[1] && !extractedColumns.includes(m[1]) && !m[1].includes(' ') && m[1].length < 35) {
      extractedColumns.push(m[1]);
    }
  }

  return { extractedRows, extractedCols, extractedColumns };
}

export const DataSummaryView: React.FC<DataSummaryProps> = ({
  totalRows: propTotalRows,
  totalCols: propTotalCols,
  columns: propColumns = [],
  markdownContent,
  onGenerateDashboard,
  message,
  metadata,
}) => {
  const [lang] = useLang();
  const [showAllCols, setShowAllCols] = useState(false);

  const { extractedRows, extractedCols, extractedColumns } = parseMetricsFromMarkdown(markdownContent);
  const extracted = extractDataMetrics((message?.content as string) || markdownContent);

  const finalTotalRows =
    propTotalRows ||
    (message?.metadata as Record<string, unknown>)?.total_rows as number ||
    (message?.metadata as Record<string, unknown>)?.totalRows as number ||
    (metadata?.total_rows as number) ||
    (metadata?.totalRows as number) ||
    extractedRows ||
    extracted.rows ||
    undefined;

  const finalTotalCols =
    propTotalCols ||
    (message?.metadata as Record<string, unknown>)?.total_cols as number ||
    (message?.metadata as Record<string, unknown>)?.totalColumns as number ||
    (metadata?.total_cols as number) ||
    (metadata?.totalColumns as number) ||
    extractedCols ||
    extracted.cols ||
    (propColumns.length > 0 ? propColumns.length : undefined) ||
    (extractedColumns.length > 0 ? extractedColumns.length : undefined) ||
    undefined;

  const displayColumns = propColumns.length > 0 ? propColumns : extractedColumns;

  const getColumnLabel = (col: string | Record<string, string>): string => {
    if (!col) return '';
    if (typeof col === 'string') return col;
    if (typeof col === 'object') {
      const name = col.name || col.field || col.headerName;
      if (name && col.type) return `${name} (${col.type})`;
      if (name) return String(name);
    }
    return String(col);
  };

  return (
    <div className="space-y-4 my-2 text-foreground">
      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        <div className="p-3 bg-accent-primary/5 border border-accent-primary/15 rounded-xl flex items-center space-x-3">
          <div className="p-2 bg-accent-primary text-white rounded-lg shrink-0 shadow-xs">
            <Database className="w-4 h-4" />
          </div>
          <div>
            <p className="text-xs font-semibold text-foreground-muted uppercase tracking-wider">{t(lang, 'summary.records')}</p>
            <p className="text-base font-bold font-mono text-foreground tabular-nums">
              {finalTotalRows ? t(lang, 'summary.recordsValue', { count: finalTotalRows.toLocaleString() }) : '--'}
            </p>
          </div>
        </div>

        <div className="p-3 bg-accent-executor/5 border border-accent-executor/15 rounded-xl flex items-center space-x-3">
          <div className="p-2 bg-accent-executor text-white rounded-lg shrink-0 shadow-xs">
            <LayoutGrid className="w-4 h-4" />
          </div>
          <div>
            <p className="text-xs font-semibold text-foreground-muted uppercase tracking-wider">{t(lang, 'summary.fields')}</p>
            <p className="text-base font-bold font-mono text-foreground tabular-nums">
              {finalTotalCols ? t(lang, 'summary.fieldsValue', { count: finalTotalCols.toLocaleString() }) : '--'}
            </p>
          </div>
        </div>

        <div className="p-3 bg-accent-verifier/5 border border-accent-verifier/15 rounded-xl flex items-center space-x-3">
          <div className="p-2 bg-accent-verifier text-white rounded-lg shrink-0 shadow-xs">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <p className="text-xs font-semibold text-foreground-muted uppercase tracking-wider">{t(lang, 'summary.quality')}</p>
            <p className="text-base font-bold text-foreground flex items-center gap-1">
              <span>{t(lang, 'summary.complete')}</span>
              <CheckCircle2 className="w-3.5 h-3.5 text-accent-verifier inline" />
            </p>
          </div>
        </div>
      </div>

      {/* Columns List */}
      {displayColumns.length > 0 && (
        <div className="p-3.5 bg-surface-raised border border-border rounded-xl space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-foreground-secondary flex items-center gap-1.5">
              <span>{t(lang, 'summary.dataFields')}</span>
              <span className="px-2 py-0.5 bg-surface-overlay text-foreground-muted text-xs font-mono rounded-full">
                {displayColumns.length}
              </span>
            </span>
            {displayColumns.length > 8 && (
              <button
                type="button"
                onClick={() => setShowAllCols(!showAllCols)}
                className="text-xs font-semibold text-accent-primary hover:text-accent-primary-hover flex items-center gap-1 hover:underline cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40 rounded px-1"
              >
                {showAllCols ? (
                  <>{t(lang, 'summary.collapse')} <ChevronUp className="w-3.5 h-3.5" /></>
                ) : (
                  <>{t(lang, 'summary.viewAll', { count: displayColumns.length })} <ChevronDown className="w-3.5 h-3.5" /></>
                )}
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5 pt-1">
            {(showAllCols ? displayColumns : displayColumns.slice(0, 8)).map((col, idx) => (
              <span
                key={idx}
                className="px-2.5 py-1 bg-surface border border-border text-foreground-secondary text-xs font-mono rounded-lg hover:border-accent-primary/30 transition-colors"
              >
                {getColumnLabel(col)}
              </span>
            ))}
            {!showAllCols && displayColumns.length > 8 && (
              <span className="px-2.5 py-1 text-xs text-foreground-muted italic bg-surface-raised/50 rounded-lg">
                {t(lang, 'summary.more', { count: displayColumns.length - 8 })}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Markdown Content */}
      <div className="prose prose-sm max-w-none">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            table({ children }) {
              return (
                <div className="overflow-x-auto my-3.5 rounded-lg border border-border shadow-xs">
                  <table className="w-full text-xs border-collapse text-left">{children}</table>
                </div>
              );
            },
            thead({ children }) {
              return <thead className="bg-surface-raised text-foreground font-bold border-b border-border uppercase tracking-wider text-xs">{children}</thead>;
            },
            tr({ children }) {
              return <tr className="border-b border-border last:border-0 hover:bg-surface-raised/50 transition-colors">{children}</tr>;
            },
            th({ children }) {
              return <th className="p-2.5 font-bold text-foreground">{children}</th>;
            },
            td({ children }) {
              const textContent = String(children || '');
              const isNumeric = /^-?\d[\d,.]*$/;
              return (
                <td className={`p-2.5 text-foreground-secondary ${isNumeric.test(textContent.trim()) ? 'font-mono text-right tabular-nums' : ''}`}>
                  {children}
                </td>
              );
            },
            h3({ children }) {
              return <h3 className="font-bold my-3 text-foreground text-base leading-snug">{children}</h3>;
            },
            h4({ children }) {
              return <h4 className="font-bold my-2.5 text-foreground-secondary text-sm flex items-center gap-1.5">{children}</h4>;
            },
            p({ children }) {
              return <p className="my-2 leading-relaxed text-foreground-secondary text-sm">{children}</p>;
            },
            strong({ children }) {
              return (
                <strong className="font-semibold text-foreground bg-accent-primary/8 px-1 py-0.5 rounded border border-accent-primary/15">
                  {children}
                </strong>
              );
            },
          }}
        >
          {markdownContent}
        </ReactMarkdown>
      </div>

      {/* CTA Button */}
      {onGenerateDashboard && (
        <div className="pt-3 border-t border-border flex items-center justify-start">
          <button
            type="button"
            onClick={onGenerateDashboard}
            className="flex items-center justify-center gap-2.5 w-full sm:w-auto px-5 py-2.5 bg-accent-primary hover:bg-accent-primary-hover text-white rounded-xl text-xs font-semibold transition-colors cursor-pointer group active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
          >
            <BarChart2 className="w-4 h-4 group-hover:scale-110 transition-transform" />
            <span>{t(lang, 'summary.buildDashboard')}</span>
          </button>
        </div>
      )}
    </div>
  );
};
