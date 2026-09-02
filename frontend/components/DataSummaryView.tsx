'use client';

import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Database, LayoutGrid, ChevronDown, ChevronUp, Sparkles, BarChart2, CheckCircle2 } from 'lucide-react';

interface DataSummaryProps {
  totalRows?: number;
  totalCols?: number;
  columns?: string[];
  markdownContent: string;
  onGenerateDashboard?: () => void;
  message?: any;
  metadata?: any;
}

// Helper trích xuất số dòng và số cột từ text nếu metadata bị thiếu
const extractDataMetrics = (text: string) => {
  let rows: number | null = null;
  let cols: number | null = null;

  if (text) {
    // 1. Tìm số dòng: Trực tiếp từ "Số lượng dòng", "Tổng số dòng", "Số bản ghi" hoặc fallback "500 dòng"
    let rowMatch = text.match(/(?:Số lượng dòng|Tổng số dòng|Số bản ghi)\D*?([0-9,.]+)/i);
    if (!rowMatch) {
      rowMatch = text.match(/([0-9,.]+)\s*(?:dòng|bản ghi)/i);
    }
    if (rowMatch && rowMatch[1]) {
      const cleaned = rowMatch[1].replace(/[,.]/g, '');
      if (cleaned) rows = parseInt(cleaned, 10);
    }

    // 2. Tìm số cột: Trực tiếp từ "Số lượng cột", "Tổng số cột", "Số trường", "Số thuộc tính" hoặc fallback "14 cột"
    let colMatch = text.match(/(?:Số lượng cột|Tổng số cột|Số trường|Số thuộc tính)\D*?([0-9,.]+)/i);
    if (!colMatch) {
      colMatch = text.match(/([0-9,.]+)\s*(?:cột|trường|thuộc tính)/i);
    }
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

  // Match total rows: e.g. "Tổng số dòng (Rows)** | `5,000`" or "5000 bản ghi"
  const rowMatch = content.match(/(?:Tổng số dòng|Số bản ghi|Số lượng dòng|\*\*Tổng số dòng\*\*)[^\n|]*[|\:]\s*`?\*?\*?([\d,.]+)/i);
  if (rowMatch) {
    const parsed = parseInt(rowMatch[1].replace(/,/g, ''), 10);
    if (!isNaN(parsed)) extractedRows = parsed;
  }

  // Match total columns: e.g. "Tổng số cột (Columns)** | `27`" or "27 thuộc tính"
  const colMatch = content.match(/(?:Tổng số cột|Số thuộc tính|Số lượng cột|\*\*Tổng số cột\*\*)[^\n|]*[|\:]\s*`?\*?\*?([\d,.]+)/i);
  if (colMatch) {
    const parsed = parseInt(colMatch[1].replace(/,/g, ''), 10);
    if (!isNaN(parsed)) extractedCols = parsed;
  }

  // Match column bullet badges: `- `col_name` (dtype)` or `- `col_name``
  const colBadgeRegex = /[\-\*]\s*`([^`]+)`/g;
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
  const [showAllCols, setShowAllCols] = useState(false);

  const { extractedRows, extractedCols, extractedColumns } = parseMetricsFromMarkdown(markdownContent);
  const extracted = extractDataMetrics(message?.content || markdownContent);

  const finalTotalRows =
    propTotalRows ||
    message?.metadata?.total_rows ||
    message?.metadata?.totalRows ||
    metadata?.total_rows ||
    metadata?.totalRows ||
    extractedRows ||
    extracted.rows ||
    undefined;

  const finalTotalCols =
    propTotalCols ||
    message?.metadata?.total_cols ||
    message?.metadata?.totalColumns ||
    metadata?.total_cols ||
    metadata?.totalColumns ||
    extractedCols ||
    extracted.cols ||
    (propColumns.length > 0 ? propColumns.length : undefined) ||
    (extractedColumns.length > 0 ? extractedColumns.length : undefined) ||
    undefined;

  const displayColumns = propColumns.length > 0 ? propColumns : extractedColumns;

  // Safe helper to convert string or object columns { name, type } to string
  const getColumnLabel = (col: any): string => {
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
    <div className="space-y-4 my-2 text-slate-900 dark:text-slate-100">
      {/* 1. KEY METRICS CARDS */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        {/* Total Records Card */}
        <div className="p-3 bg-blue-50/80 dark:bg-blue-950/40 border border-blue-200/60 dark:border-blue-800/60 rounded-xl flex items-center space-x-3 shadow-2xs">
          <div className="p-2 bg-blue-500 text-white rounded-lg shrink-0 shadow-xs">
            <Database className="w-4 h-4" />
          </div>
          <div>
            <p className="text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Tổng số bản ghi
            </p>
            <p className="text-base font-bold text-slate-800 dark:text-slate-100">
              {finalTotalRows ? `${finalTotalRows.toLocaleString()} dòng` : '--'}
            </p>
          </div>
        </div>

        {/* Total Columns Card */}
        <div className="p-3 bg-indigo-50/80 dark:bg-indigo-950/40 border border-indigo-200/60 dark:border-indigo-800/60 rounded-xl flex items-center space-x-3 shadow-2xs">
          <div className="p-2 bg-indigo-500 text-white rounded-lg shrink-0 shadow-xs">
            <LayoutGrid className="w-4 h-4" />
          </div>
          <div>
            <p className="text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Số trường dữ liệu
            </p>
            <p className="text-base font-bold text-slate-800 dark:text-slate-100">
              {finalTotalCols ? `${finalTotalCols.toLocaleString()} cột` : '--'}
            </p>
          </div>
        </div>

        {/* Data Quality Card */}
        <div className="p-3 bg-emerald-50/80 dark:bg-emerald-950/40 border border-emerald-200/60 dark:border-emerald-800/60 rounded-xl flex items-center space-x-3 shadow-2xs">
          <div className="p-2 bg-emerald-500 text-white rounded-lg shrink-0 shadow-xs">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <p className="text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Chất lượng dữ liệu
            </p>
            <p className="text-base font-bold text-slate-800 dark:text-slate-100 flex items-center gap-1">
              <span>Hoàn thiện</span>
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 inline" />
            </p>
          </div>
        </div>
      </div>

      {/* 2. COLLAPSIBLE COLUMNS LIST */}
      {displayColumns.length > 0 && (
        <div className="p-3.5 bg-slate-50/80 dark:bg-slate-900/90 border border-slate-200/80 dark:border-slate-800 rounded-xl space-y-2 shadow-2xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
              <span>Danh sách trường dữ liệu</span>
              <span className="px-2 py-0.5 bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-slate-400 text-[10px] font-mono rounded-full">
                {displayColumns.length}
              </span>
            </span>
            {displayColumns.length > 8 && (
              <button
                type="button"
                onClick={() => setShowAllCols(!showAllCols)}
                className="text-xs font-semibold text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 flex items-center gap-1 hover:underline cursor-pointer transition-colors"
              >
                {showAllCols ? (
                  <>
                    Thu gọn <ChevronUp className="w-3.5 h-3.5" />
                  </>
                ) : (
                  <>
                    Xem tất cả ({displayColumns.length}) <ChevronDown className="w-3.5 h-3.5" />
                  </>
                )}
              </button>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5 pt-1">
            {(showAllCols ? displayColumns : displayColumns.slice(0, 8)).map((col, idx) => (
              <span
                key={idx}
                className="px-2.5 py-1 bg-white dark:bg-slate-800 border border-slate-200/90 dark:border-slate-700/80 text-slate-700 dark:text-slate-300 text-[11px] font-mono rounded-lg shadow-2xs hover:border-blue-300 dark:hover:border-blue-700 transition-colors"
              >
                {getColumnLabel(col)}
              </span>
            ))}
            {!showAllCols && displayColumns.length > 8 && (
              <span className="px-2.5 py-1 text-[11px] text-slate-400 dark:text-slate-500 italic bg-slate-100/50 dark:bg-slate-800/30 rounded-lg">
                +{displayColumns.length - 8} cột khác...
              </span>
            )}
          </div>
        </div>
      )}

      {/* 3. MARKDOWN TABLE CONTENT (CUSTOM STYLED) */}
      <div className="prose prose-slate dark:prose-invert max-w-none">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            table({ children }) {
              return (
                <div className="overflow-x-auto my-3.5 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xs">
                  <table className="w-full text-xs border-collapse text-left">{children}</table>
                </div>
              );
            },
            thead({ children }) {
              return (
                <thead className="bg-slate-100/90 dark:bg-slate-800/90 text-slate-700 dark:text-slate-200 font-bold border-b border-slate-200 dark:border-slate-700 uppercase tracking-wider text-[11px]">
                  {children}
                </thead>
              );
            },
            tr({ children }) {
              return (
                <tr className="odd:bg-white dark:odd:bg-slate-900/90 even:bg-slate-50/70 dark:even:bg-slate-800/40 hover:bg-blue-50/50 dark:hover:bg-slate-800/80 transition-colors border-b border-slate-100 dark:border-slate-800/60 last:border-0">
                  {children}
                </tr>
              );
            },
            th({ children }) {
              return <th className="p-2.5 font-bold text-slate-800 dark:text-slate-200">{children}</th>;
            },
            td({ children }) {
              const textContent = String(children || '');
              const isNumeric = /^-?\d[\d,.]*$/;
              return (
                <td
                  className={`p-2.5 text-slate-700 dark:text-slate-300 ${
                    isNumeric.test(textContent.trim()) ? 'font-mono text-right' : ''
                  }`}
                >
                  {children}
                </td>
              );
            },
            h3({ children }) {
              return (
                <h3 className="border-l-4 border-blue-500 font-bold pl-3 my-3 text-slate-900 dark:text-slate-100 text-base leading-snug">
                  {children}
                </h3>
              );
            },
            h4({ children }) {
              return (
                <h4 className="font-bold my-2.5 text-slate-800 dark:text-slate-200 text-sm flex items-center gap-1.5">
                  {children}
                </h4>
              );
            },
            p({ children }) {
              return <p className="my-2 leading-relaxed text-slate-800 dark:text-slate-200 text-sm">{children}</p>;
            },
            strong({ children }) {
              return (
                <strong className="font-semibold text-slate-900 dark:text-slate-100 bg-blue-50 dark:bg-blue-950/40 px-1 py-0.5 rounded border border-blue-100 dark:border-blue-900/30">
                  {children}
                </strong>
              );
            },
          }}
        >
          {markdownContent}
        </ReactMarkdown>
      </div>

      {/* 4. CALL-TO-ACTION BUTTON */}
      {onGenerateDashboard && (
        <div className="pt-3 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-start">
          <button
            type="button"
            onClick={onGenerateDashboard}
            className="flex items-center justify-center gap-2.5 w-full sm:w-auto px-5 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white rounded-xl text-xs font-semibold shadow-xs hover:shadow-md transition-all cursor-pointer group active:scale-[0.98]"
          >
            <BarChart2 className="w-4 h-4 group-hover:scale-110 transition-transform" />
            <span>📌 Dựng Dashboard trực quan từ dữ liệu này</span>
          </button>
        </div>
      )}
    </div>
  );
};
