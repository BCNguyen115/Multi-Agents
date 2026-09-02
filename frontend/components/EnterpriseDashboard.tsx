'use client';

import React, { useState, useMemo } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { ColDef, GridOptions } from 'ag-grid-community';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from 'recharts';
import { CSVMetadata } from '../lib/types';
import { Filter, BarChart3, Table as TableIcon, TrendingUp, Layers, Hash } from 'lucide-react';

interface EnterpriseDashboardProps {
  metadata: CSVMetadata;
  generatedCode?: string;
}

const CORPORATE_COLORS = ['#003366', '#2563EB', '#0284C7', '#0d9488', '#059669', '#d97706'];

export const EnterpriseDashboard: React.FC<EnterpriseDashboardProps> = ({ metadata }) => {
  // Slicers state
  const [selectedFilters, setSelectedFilters] = useState<Record<string, string[]>>({});

  // Filter sample data client-side based on Slicers
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

  // Helper to identify ID / Key columns
  const isIdColumn = (colName: string) => {
    const k = colName.toLowerCase();
    return (
      k === 'id' ||
      k.includes('id_') ||
      k.endsWith('_id') ||
      k.includes('code') ||
      k.includes('zip') ||
      k.includes('phone') ||
      k.includes('index') ||
      k.includes('ssn') ||
      k.endsWith('_num') ||
      k.endsWith('number')
    );
  };

  // Compute KPI values (excluding ID columns)
  const totalRowsCount = metadata.totalRows;
  const cleanNumericCols = useMemo(() => {
    return metadata.numericCols.filter((col) => !isIdColumn(col));
  }, [metadata.numericCols]);

  const primaryNumericCol = cleanNumericCols[0] || '';
  const secondaryNumericCol = cleanNumericCols[1] || '';

  const primarySum = useMemo(() => {
    if (metadata.summary[primaryNumericCol]?.sum) {
      return metadata.summary[primaryNumericCol].sum!;
    }
    return filteredData.reduce((acc, curr) => acc + (Number(curr[primaryNumericCol]) || 0), 0);
  }, [primaryNumericCol, metadata.summary, filteredData]);

  const primaryAvg = useMemo(() => {
    if (metadata.summary[primaryNumericCol]?.avg) {
      return metadata.summary[primaryNumericCol].avg!;
    }
    return totalRowsCount ? primarySum / totalRowsCount : 0;
  }, [primaryNumericCol, primarySum, totalRowsCount, metadata.summary]);

  const secondarySum = useMemo(() => {
    if (metadata.summary[secondaryNumericCol]?.sum) {
      return metadata.summary[secondaryNumericCol].sum!;
    }
    return filteredData.reduce((acc, curr) => acc + (Number(curr[secondaryNumericCol]) || 0), 0);
  }, [secondaryNumericCol, metadata.summary, filteredData]);

  // Dynamic AG Grid Column Definitions
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

  // AG Grid Options
  const gridOptions: GridOptions = {
    pagination: true,
    paginationPageSize: 10,
    domLayout: 'normal',
  };

  // Recharts Data Aggregation
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

  return (
    <div className="space-y-6 my-4 bg-slate-50 p-6 rounded-2xl border border-slate-200 shadow-xs">
      {/* Dashboard Title Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-slate-200 pb-4 gap-3">
        <div>
          <h2 className="text-xl font-bold text-slate-900 flex items-center gap-2">
            <Layers className="w-6 h-6 text-brand-700" />
            Executive Enterprise Dashboard
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Engineered by <span className="font-semibold text-slate-700">DuckDB-Wasm</span> & Recharts / AG Grid React
          </p>
        </div>

        <div className="flex items-center space-x-2 text-xs bg-white border border-slate-200 px-3 py-1.5 rounded-lg shadow-2xs">
          <Hash className="w-4 h-4 text-brand-600" />
          <span className="text-slate-600">Total Rows:</span>
          <span className="font-bold text-slate-900">{totalRowsCount.toLocaleString()}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* =========================================================================
            TẦNG 2: SIDEBAR SLICERS (GLOBAL FILTERS)
           ========================================================================= */}
        <div className="lg:col-span-1 bg-white p-4 rounded-xl border border-slate-200 shadow-2xs space-y-4">
          <div className="flex items-center space-x-2 font-bold text-slate-800 text-sm border-b border-slate-100 pb-2">
            <Filter className="w-4 h-4 text-brand-600" />
            <span>Sidebar Slicers (Bộ Lọc)</span>
          </div>

          {metadata.categoricalCols.length === 0 ? (
            <p className="text-xs text-slate-400 italic">Không có cột phân loại nào để lọc.</p>
          ) : (
            metadata.categoricalCols.slice(0, 3).map((catCol) => {
              const uniqueVals = Array.from(
                new Set(metadata.sampleData.map((r) => String(r[catCol])).filter(Boolean))
              );

              return (
                <div key={catCol} className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-700">
                    Lọc theo {catCol.replace(/_/g, ' ')}:
                  </label>
                  <select
                    multiple
                    value={selectedFilters[catCol] || []}
                    onChange={(e) => {
                      const options = Array.from(e.target.selectedOptions, (option) => option.value);
                      setSelectedFilters((prev) => ({ ...prev, [catCol]: options }));
                    }}
                    className="w-full text-xs border border-slate-300 rounded-lg p-2 bg-slate-50 focus:ring-2 focus:ring-brand-500 focus:outline-none min-h-[80px]"
                  >
                    {uniqueVals.map((val) => (
                      <option key={val} value={val}>
                        {val}
                      </option>
                    ))}
                  </select>
                  <p className="text-[10px] text-slate-400">Giữ Ctrl / Cmd để chọn nhiều giá trị</p>
                </div>
              );
            })
          )}
        </div>

        <div className="lg:col-span-3 space-y-6">
          {/* =========================================================================
              TẦNG 3: KPI METRICS CARDS
             ========================================================================= */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs border-l-4 border-l-brand-700 hover:shadow-md transition-shadow">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Tổng Số Bản Ghi</p>
              <p className="text-2xl font-extrabold text-brand-700 mt-1">{totalRowsCount.toLocaleString()}</p>
            </div>

            {primaryNumericCol && (
              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs border-l-4 border-l-brand-500 hover:shadow-md transition-shadow">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Tổng {primaryNumericCol.replace(/_/g, ' ')}
                </p>
                <p className="text-2xl font-extrabold text-brand-700 mt-1">
                  {primarySum.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </p>
              </div>
            )}

            {primaryNumericCol && (
              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs border-l-4 border-l-teal-600 hover:shadow-md transition-shadow">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Trung Bình {primaryNumericCol.replace(/_/g, ' ')}
                </p>
                <p className="text-2xl font-extrabold text-teal-700 mt-1">
                  {primaryAvg.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </p>
              </div>
            )}
          </div>

          {/* =========================================================================
              TẦNG 4: PLOTLY / RECHARTS INTERACTIVE CHARTS GRID
             ========================================================================= */}
          <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs space-y-4">
            <div className="flex items-center space-x-2 font-bold text-slate-800 text-sm border-b border-slate-100 pb-3">
              <BarChart3 className="w-4 h-4 text-brand-600" />
              <span>Phân Tích Trực Quan Hóa (Responsive Charts)</span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Bar Chart */}
              <div className="h-64">
                <p className="text-xs font-semibold text-slate-600 mb-2 text-center">
                  Phân bổ theo {primaryCatCol.replace(/_/g, ' ')}
                </p>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Bar dataKey="value" fill="#003366" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Donut Chart */}
              <div className="h-64">
                <p className="text-xs font-semibold text-slate-600 mb-2 text-center">
                  Tỷ trọng phân loại {primaryCatCol.replace(/_/g, ' ')}
                </p>
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={chartData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      innerRadius={45}
                      outerRadius={75}
                      paddingAngle={3}
                    >
                      {chartData.map((_, index) => (
                        <Cell key={`cell-${index}`} fill={CORPORATE_COLORS[index % CORPORATE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend wrapperStyle={{ fontSize: '11px' }} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* =========================================================================
          TẦNG 5: ENTERPRISE AGGRID REACT TABLE
         ========================================================================= */}
      <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs space-y-3">
        <div className="flex items-center justify-between border-b border-slate-100 pb-3">
          <div className="flex items-center space-x-2 font-bold text-slate-800 text-sm">
            <TableIcon className="w-4 h-4 text-brand-600" />
            <span>Enterprise AG Grid Table (Sort, Group, Filter, Pagination)</span>
          </div>
          <span className="text-xs text-slate-500 font-mono">ag-grid-react v31</span>
        </div>

        <div className="ag-theme-alpine w-full h-80 rounded-lg overflow-hidden border border-slate-200">
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
