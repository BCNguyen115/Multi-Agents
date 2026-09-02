'use client';

import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import ReactECharts from 'echarts-for-react';
import { EChartComponent } from './EChartComponent';
import { AgGridReact } from 'ag-grid-react';
import { ColDef, GridOptions } from 'ag-grid-community';
import { DashboardSpec, ChartItem, KPIItem, TableColumn } from '../../lib/types';
import {
  Filter,
  BarChart3,
  Table as TableIcon,
  Maximize2,
  Minimize2,
  Download,
  Sparkles,
  TrendingUp,
  TrendingDown,
  Minus,
  LayoutDashboard,
  RefreshCw,
  Search,
  Printer,
  DollarSign,
  ShoppingBag,
  Layers,
  Users,
  Lightbulb,
  CreditCard,
  Award,
  Target,
  Database,
  Hash,
  Tag,
} from 'lucide-react';

interface DynamicDashboardProps {
  spec: DashboardSpec;
}

// Helper tìm giá trị trong row bất kể cách đặt tên key của LLM
function getFlexibleRowValue(row: Record<string, any>, targetKey: string): any {
  if (!row || !targetKey) return undefined;

  // 1. Khớp chính xác
  if (row[targetKey] !== undefined) return row[targetKey];

  // Chuẩn hóa targetKey về chữ thường, bỏ khoảng trắng và gạch dưới
  const normalize = (str: string) => str.toLowerCase().replace(/[^a-z0-9]/g, '');
  const cleanTarget = normalize(targetKey);

  // 2. Tìm key trong row có dạng chuẩn hóa tương đương
  const foundKey = Object.keys(row).find((k) => normalize(k) === cleanTarget);
  if (foundKey && row[foundKey] !== undefined) {
    return row[foundKey];
  }

  return undefined;
}

const CORPORATE_PALETTE = [
  '#4F46E5', '#0D9488', '#F59E0B', '#E11D48',
  '#2563EB', '#64748B', '#7C3AED', '#059669',
];

export const DynamicDashboard: React.FC<DynamicDashboardProps> = ({ spec }) => {
  const [isMounted, setIsMounted] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [selectedFilters, setSelectedFilters] = useState<Record<string, string[]>>({});
  const [quickFilterText, setQuickFilterText] = useState('');
  const gridRef = useRef<AgGridReact>(null);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  // Extract raw data rows from spec.table
  const rawRows = useMemo(() => {
    if (spec?.table?.rows && Array.isArray(spec.table.rows)) {
      return spec.table.rows;
    }
    return [];
  }, [spec]);

  // Helper to detect ID / Key columns
  const isIdColumn = (colName: string, uniqueRatio: number) => {
    const k = colName.toLowerCase();
    const isKeyword = (
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
    return isKeyword || uniqueRatio >= 0.95;
  };

  // Identify slicers (Categorical non-ID columns with 2 to 15 unique values, maximum 4 slicers)
  const filterCategories = useMemo(() => {
    const categoryCols = (spec as any)?.valid_category_cols || (spec as any)?.validCategoryCols || [];
    let candidates: string[] = [];

    if (Array.isArray(categoryCols) && categoryCols.length > 0) {
      candidates = categoryCols.filter((col: string) => {
        const uniqueVals = new Set((rawRows || []).map((r: Record<string, any>) => String(r[col] ?? '')));
        return uniqueVals.size >= 2 && uniqueVals.size <= 15;
      });
    }

    if (candidates.length === 0 && rawRows.length > 0) {
      const keys = Object.keys(rawRows[0] || {});
      const totalCount = rawRows.length;

      candidates = keys.filter((key) => {
        const sampleVal = rawRows[0][key];
        // Ignore numeric metrics for dropdown slicers
        if (typeof sampleVal === 'number') return false;

        const uniqueVals = new Set(rawRows.map((r) => String(r[key] ?? '')));
        const uniqueCount = uniqueVals.size;
        const uniqueRatio = totalCount > 0 ? uniqueCount / totalCount : 0;

        if (isIdColumn(key, uniqueRatio)) return false;

        return uniqueCount >= 2 && uniqueCount <= 15;
      });
    }

    return candidates.slice(0, 4);
  }, [rawRows, spec?.valid_category_cols]);

  // Client-side row filtering across Slicers and Cross-filtering
  const filteredRows = useMemo(() => {
    if (Object.keys(selectedFilters).length === 0) return rawRows;

    return rawRows.filter((row) => {
      for (const [colKey, selectedVals] of Object.entries(selectedFilters)) {
        if (selectedVals && selectedVals.length > 0) {
          const rowVal = String(row[colKey] ?? '');
          if (!selectedVals.includes(rowVal)) {
            return false;
          }
        }
      }
      return true;
    });
  }, [rawRows, selectedFilters]);

  // Render strictly valid KPI Cards without padding dummy cards ("THỐNG KÊ 4")
  const displayKpis = useMemo(() => {
    const rawKpis: KPIItem[] = (spec?.kpis && spec.kpis.length > 0) ? spec.kpis : ((spec as any)?.kpiCards || []);
    return rawKpis.filter((kpi) => {
      const title = (kpi?.title || '').toUpperCase();
      return !title.includes('THỐNG KÊ 4') && !title.includes('KPI 4') && !title.includes('FALLBACK');
    });
  }, [spec?.kpis, (spec as any)?.kpiCards]);

  // Structured Data Storytelling AI Insights (Diễn Biến -> Nguyên Nhân -> Khuyến Nghị)
  const storytellingInsights = useMemo(() => {
    let dienBien = '';
    let nguyenNhan = '';
    let khuyenNghi = '';

    const summaryText: string = String(spec?.summaryText || spec?.summary || '');
    if (summaryText) {
      const dienBienMatch = summaryText.match(/(?:📈|Diễn biến[:\s]*)([^🔍🎯\n]*)/i);
      const nguyenNhanMatch = summaryText.match(/(?:🔍|Nguyên nhân[:\s]*)([^🎯📈\n]*)/i);
      const khuyenNghiMatch = summaryText.match(/(?:🎯|Khuyến nghị[:\s]*)([^📈🔍\n]*)/i);

      if (dienBienMatch && dienBienMatch[1].trim()) dienBien = dienBienMatch[1].trim();
      if (nguyenNhanMatch && nguyenNhanMatch[1].trim()) nguyenNhan = nguyenNhanMatch[1].trim();
      if (khuyenNghiMatch && khuyenNghiMatch[1].trim()) khuyenNghi = khuyenNghiMatch[1].trim();

      if (!dienBien || !nguyenNhan || !khuyenNghi) {
        const sentences = summaryText.split('.').map((s: string) => s.trim()).filter((s: string) => s.length > 5);
        if (!dienBien && sentences[0]) dienBien = sentences[0];
        if (!nguyenNhan && sentences[1]) nguyenNhan = sentences[1];
        if (!khuyenNghi && sentences[2]) khuyenNghi = sentences[2];
      }
    }

    if (!dienBien && rawRows.length > 0) {
      dienBien = `Tổng số bản ghi phân tích đạt ${rawRows.length.toLocaleString()} dòng dữ liệu với quy mô chỉ số tổng hợp phát triển tăng trưởng ổn định.`;
    }
    if (!nguyenNhan && filterCategories.length > 0 && rawRows.length > 0) {
      const catCol = filterCategories[0];
      const counts: Record<string, number> = {};
      rawRows.forEach((r) => {
        const val = String(r[catCol] ?? 'Khác');
        counts[val] = (counts[val] || 0) + 1;
      });
      const topEntry = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
      if (topEntry) {
        nguyenNhan = `Nhóm phân loại [${topEntry[0]}] đóng vai trò động lực chính với ${topEntry[1].toLocaleString()} bản ghi (chiếm tỷ trọng cao nhất).`;
      }
    }
    if (!nguyenNhan) {
      nguyenNhan = `Cơ cấu phân bổ tập trung vào các nhóm chỉ số doanh thu trọng điểm mang lại hiệu quả vận hành tối ưu.`;
    }
    if (!khuyenNghi) {
      khuyenNghi = `Khuyến nghị ban điều hành đẩy mạnh chiến dịch cho phân khúc chủ lực và tối ưu hóa chi phí vận hành cho các nhóm bán chậm.`;
    }

    return [
      {
        phase: 'Diễn Biến',
        tag: '📈 Bức Tranh Toàn Cảnh',
        color: 'from-blue-50 to-indigo-50/70 border-blue-200 text-blue-950',
        icon: TrendingUp,
        text: dienBien,
      },
      {
        phase: 'Nguyên Nhân',
        tag: '🔍 Động Lực Chính',
        color: 'from-amber-50 to-orange-50/70 border-amber-200 text-amber-950',
        icon: Search,
        text: nguyenNhan,
      },
      {
        phase: 'Khuyến Nghị',
        tag: '🎯 Hành Động Chiến Lược',
        color: 'from-emerald-50 to-teal-50/70 border-emerald-200 text-emerald-950',
        icon: Target,
        text: khuyenNghi,
      },
    ];
  }, [spec.summary, rawRows, filterCategories]);

  // Export CSV handler
  const onExportCSV = useCallback(() => {
    if (gridRef.current && gridRef.current.api) {
      gridRef.current.api.exportDataAsCsv({
        fileName: `${spec.dashboard_title || 'Executive_Dashboard'}_Export.csv`,
      });
    }
  }, [spec.dashboard_title]);

  // Print PDF report handler
  const onPrintReport = useCallback(() => {
    window.print();
  }, []);

  // Reset all filters
  const handleResetFilters = useCallback(() => {
    setSelectedFilters({});
    setQuickFilterText('');
  }, []);

  // Cross-filtering click handler on charts with Universal Column Lookup
  const handleChartClick = useCallback(
    (params: any, chartConfig?: any) => {
      if (!params || !params.name) return;

      const clickedValue = String(params.name).trim();
      if (!clickedValue) return;

      // 1. Tìm tên cột chính xác tương ứng với giá trị được click
      let matchedColumnKey = chartConfig?.x_axis_key || chartConfig?.name_key || chartConfig?.xAxisKey;

      // 2. Fallback: Nếu chartConfig không truyền key, hoặc key không tồn tại trong rawRows, quét các cột trong rawRows để tìm cột chứa giá trị clickedValue
      if (!matchedColumnKey && rawRows.length > 0) {
        const sampleRow = rawRows[0];
        matchedColumnKey = Object.keys(sampleRow).find((key) => {
          return rawRows.some((row) => String(row[key] ?? '').trim() === clickedValue);
        });
      }

      // Dual-check: Nếu matchedColumnKey từ chartConfig không nằm trực tiếp trong keys của rawRows[0], quét rawRows để tìm đúng tên cột thực tế
      if (matchedColumnKey && rawRows.length > 0 && !(matchedColumnKey in rawRows[0])) {
        const foundKeyInRows = Object.keys(rawRows[0]).find((key) => {
          return rawRows.some((row) => String(row[key] ?? '').trim() === clickedValue);
        });
        if (foundKeyInRows) {
          matchedColumnKey = foundKeyInRows;
        }
      }

      // 3. Nếu vẫn không tìm thấy, mới fallback về filterCategories[0]
      const targetCol = matchedColumnKey || filterCategories[0] || 'category';

      // 4. Set state bộ lọc
      setSelectedFilters((prev) => {
        const currentVals = prev[targetCol] || [];
        if (currentVals.includes(clickedValue)) {
          // Toggle OFF nếu click lại
          const filtered = currentVals.filter((v) => v !== clickedValue);
          const updated = { ...prev };
          if (filtered.length > 0) {
            updated[targetCol] = filtered;
          } else {
            delete updated[targetCol];
          }
          return updated;
        } else {
          // Toggle ON
          return { ...prev, [targetCol]: [clickedValue] };
        }
      });
    },
    [rawRows, filterCategories]
  );

  // AG Grid column definitions
  const columnDefs: ColDef[] = useMemo(() => {
    if (spec.table && spec.table.columns && spec.table.columns.length > 0) {
      return spec.table.columns.map((col: TableColumn) => ({
        field: col.field,
        headerName: col.headerName || col.field.replace(/_/g, ' ').toUpperCase(),
        sortable: col.sortable ?? true,
        filter: true,
        resizable: true,
        valueFormatter: (params) => {
          if (typeof params.value === 'number') {
            if (col.field.toLowerCase().includes('revenue') || col.field.toLowerCase().includes('price') || col.field.toLowerCase().includes('sales')) {
              return `$${params.value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
            }
            return params.value.toLocaleString();
          }
          return params.value;
        },
      }));
    }

    if (rawRows.length > 0) {
      return Object.keys(rawRows[0]).map((key) => ({
        field: key,
        headerName: key.replace(/_/g, ' ').toUpperCase(),
        sortable: true,
        filter: true,
        resizable: true,
      }));
    }

    return [];
  }, [spec.table, rawRows]);

  const gridOptions: GridOptions = {
    pagination: true,
    paginationPageSize: 20,
    paginationPageSizeSelector: [10, 20, 50, 100, 500],
  };

  // Helper: Extract numeric value safely from numbers or formatted strings ("$2,500.00", "1,500")
  const parseNumericValue = (val: any): number => {
    if (typeof val === 'number') return isNaN(val) ? 0 : val;
    if (!val) return 0;
    const cleaned = String(val).replace(/[^0-9.-]+/g, '');
    const num = parseFloat(cleaned);
    return isNaN(num) ? 0 : num;
  };

  // Dynamic ECharts option generator computed directly from active filteredRows (0ms reactive state)
  const getDynamicChartOption = useCallback(
    (chartConfig: ChartItem, isPie: boolean) => {
      const { type, x_axis_key, name_key, series_keys, value_key, title } = chartConfig;

      const sampleRow = filteredRows[0] || rawRows[0] || {};
      const availableKeys = Object.keys(sampleRow);

      const catField =
        x_axis_key ||
        name_key ||
        filterCategories[0] ||
        availableKeys.find((k) => typeof sampleRow[k] === 'string' && !isIdColumn(k, 0)) ||
        availableKeys[0] ||
        'category';

      const numField =
        (series_keys && series_keys[0]) ||
        value_key ||
        availableKeys.find((k) => {
          if (isIdColumn(k, 0)) return false;
          const parsed = parseNumericValue(sampleRow[k]);
          return parsed > 0;
        }) ||
        'revenue';

      const rowsToAggregate = filteredRows.length > 0 ? filteredRows : rawRows;

      if (isPie || String(type) === 'pie' || String(type) === 'donut') {
        let pieData: { name: string; value: number }[] = [];

        if (chartConfig.data && Array.isArray(chartConfig.data) && chartConfig.data.length > 0) {
          pieData = chartConfig.data.map((item: any) => {
            const rawName = item.name ?? item.x ?? item.category ?? item.label ?? 'Khác';
            const nameStr = (rawName !== undefined && rawName !== null && String(rawName).trim() !== '' && String(rawName) !== 'undefined' && String(rawName) !== 'null')
              ? String(rawName)
              : 'Khác';
            const rawVal = item.value ?? item.y ?? item.count ?? 0;
            const numVal = typeof rawVal === 'number' ? rawVal : parseNumericValue(rawVal);
            return { name: nameStr, value: numVal };
          });
        } else {
          const targetNameKey = name_key || catField;
          const targetValKey = value_key || numField;

          const groupedPie = rowsToAggregate.reduce((acc, row) => {
            const rawKey = getFlexibleRowValue(row, targetNameKey) ?? getFlexibleRowValue(row, catField);
            const keyName = (rawKey !== undefined && rawKey !== null && String(rawKey).trim() !== '' && String(rawKey) !== 'undefined' && String(rawKey) !== 'null')
              ? String(rawKey)
              : 'Khác';

            const rawVal = getFlexibleRowValue(row, targetValKey) ?? getFlexibleRowValue(row, numField) ?? getFlexibleRowValue(row, 'revenue') ?? 0;
            const numVal = typeof rawVal === 'number' ? rawVal : parseNumericValue(rawVal);

            acc[keyName] = (acc[keyName] || 0) + numVal;
            return acc;
          }, {} as Record<string, number>);

          pieData = Object.entries(groupedPie).map(([name, value]) => ({ name, value }));
        }

        return {
          title: {
            text: title || 'Tỷ Lệ Phương Thức Thanh Toán',
            left: 'center',
            textStyle: { fontSize: 14, fontWeight: 'bold', color: '#1E293B' },
          },
          tooltip: {
            trigger: 'item',
            formatter: (params: any) => {
              const isMonetary = Boolean((chartConfig as any)?.isMonetary);
              const valFormatted = (typeof params.value === 'number' && isMonetary)
                ? `$${params.value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                : (typeof params.value === 'number' ? params.value.toLocaleString() : params.value);
              return `<b>${params.name}</b>: ${valFormatted} (${params.percent}%)`;
            },
          },
          legend: {
            show: true,
            type: 'scroll',
            bottom: 0,
            textStyle: { fontSize: 11, color: '#475569' },
          },
          color: ['#4F46E5', '#F37021', '#10B981', '#06B6D4', '#8B5CF6', '#EC4899', '#F59E0B'],
          series: [
            {
              type: 'pie',
              radius: ['40%', '70%'],
              avoidLabelOverlap: true,
              minAngle: 5,
              itemStyle: { borderRadius: 6, borderColor: '#ffffff', borderWidth: 2 },
              label: {
                show: true,
                formatter: '{b}: {d}%',
                fontSize: 11,
                color: '#334155',
              },
              emphasis: {
                label: { show: true, fontSize: 12, fontWeight: 'bold' },
                itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.2)' },
              },
              data: pieData.length > 0 ? pieData : [{ name: 'Không có dữ liệu', value: 0 }],
            },
          ],
        };
      }

      // Bar / Line Chart dynamic aggregation from filteredRows
      const targetXKey = x_axis_key || catField;
      const targetSeriesKey = (series_keys && series_keys[0]) || numField;

      const grouped = rowsToAggregate.reduce((acc, row) => {
        const rawKey = getFlexibleRowValue(row, targetXKey) ?? getFlexibleRowValue(row, catField);
        const keyName = (rawKey !== undefined && rawKey !== null && String(rawKey).trim() !== '' && String(rawKey) !== 'undefined' && String(rawKey) !== 'null')
          ? String(rawKey)
          : 'Khác';

        const rawVal = getFlexibleRowValue(row, targetSeriesKey) ?? getFlexibleRowValue(row, numField) ?? getFlexibleRowValue(row, 'revenue') ?? 0;
        const numVal = typeof rawVal === 'number' ? rawVal : parseNumericValue(rawVal);

        acc[keyName] = (acc[keyName] || 0) + numVal;
        return acc;
      }, {} as Record<string, number>);

      const xAxisData = Object.keys(grouped);
      const seriesData = Object.values(grouped);
      const isLine = type === 'line';

      return {
        title: {
          text: title || 'Phân Tích Doanh Số Theo Nhóm',
          left: 'left',
          textStyle: { fontSize: 13, fontWeight: 'bold', color: '#1E293B' },
        },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross', crossStyle: { color: '#94A3B8' } },
          formatter: (params: any) => {
            if (Array.isArray(params) && params.length > 0) {
              const item = params[0];
              const valFormatted = typeof item.value === 'number' ? `$${item.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : item.value;
              return `<div style="font-weight:bold;margin-bottom:4px;">${item.axisValueLabel}</div><div><span style="display:inline-block;margin-right:4px;border-radius:10px;width:10px;height:10px;background-color:${item.color};"></span>${item.seriesName}: <b>${valFormatted}</b></div>`;
            }
            return '';
          },
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '12%',
          containLabel: true,
        },
        xAxis: {
          type: 'category',
          data: xAxisData,
          axisLabel: { interval: 0, rotate: xAxisData.length > 8 ? 30 : 0, fontSize: 10, color: '#475569' },
          axisLine: { lineStyle: { color: '#CBD5E1' } },
        },
        yAxis: {
          type: 'value',
          axisLabel: {
            fontSize: 10,
            color: '#475569',
            formatter: (val: number) => {
              const isMonetary = Boolean((chartConfig as any)?.isMonetary);
              if (isMonetary) {
                return val >= 1000000 ? `$${(val / 1000000).toFixed(1)}M` : val >= 1000 ? `$${(val / 1000).toFixed(0)}K` : `$${val.toLocaleString()}`;
              }
              return val >= 1000000 ? `${(val / 1000000).toFixed(1)}M` : val >= 1000 ? `${(val / 1000).toFixed(0)}K` : `${val.toLocaleString()}`;
            },
          },
          splitLine: { lineStyle: { type: 'dashed', color: '#F1F5F9' } },
        },
        series: [
          {
            name: numField.replace(/_/g, ' ').toUpperCase(),
            type: isLine ? 'line' : 'bar',
            smooth: true,
            barMaxWidth: 40,
            itemStyle: {
              color: CORPORATE_PALETTE[0],
              borderRadius: isLine ? 0 : [6, 6, 0, 0],
            },
            data: seriesData,
          },
        ],
      };
    },
    [filteredRows, rawRows, filterCategories]
  );

  const primaryChart = spec.charts?.[0];
  const secondaryChart = spec.charts?.[1] || spec.charts?.[0];

  const displayTotalRows = spec?.totalRows ?? spec?.total_rows ?? spec?.total_records ?? rawRows.length ?? 0;
  const displayTotalCols = spec?.totalColumns ?? spec?.total_cols ?? spec?.total_fields ?? 0;

  const hasActiveFilters = Object.keys(selectedFilters).length > 0 || quickFilterText.trim().length > 0;

  const isSingleChart =
    spec?.layout_type === 'single_chart' ||
    (spec as any)?.layout?.layout_type === 'single_chart' ||
    (spec?.charts?.length === 1 && (!displayKpis || displayKpis.length === 0));

  if (!isMounted) {
    return <div className="min-h-[500px] w-full animate-pulse bg-slate-50 rounded-2xl border border-slate-200 my-4" />;
  }

  return (
    <div
      className={`transition-all duration-300 ${isFullscreen
          ? 'fixed inset-0 z-50 overflow-y-auto bg-slate-100 p-6 shadow-2xl'
          : 'w-full space-y-6 my-4 bg-slate-50/90 p-5 rounded-2xl border border-slate-200 shadow-sm min-h-[500px]'
        }`}
    >
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-4">
        <div className="flex items-center space-x-3">
          <div className="p-2.5 bg-brand-700 text-white rounded-xl shadow-xs">
            <LayoutDashboard className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-xl font-extrabold text-slate-900 tracking-tight flex items-center gap-2">
              {spec?.datasetName
                ? `${spec.datasetName.replace(/\.[^/.]+$/, "").toUpperCase()} ${isSingleChart ? 'Chart View' : 'Analytics Dashboard'}`
                : spec?.dashboard_title || 'Dataset Analytics View'}
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {displayTotalRows > 0
                ? `Phân tích tự động dựa trên ${displayTotalRows.toLocaleString()} dòng dữ liệu và ${displayTotalCols > 0 ? displayTotalCols.toLocaleString() : '--'} trường.`
                : 'Hệ thống Multi-Agent BI • Phân tích real-time & tương tác chéo'}
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2 shrink-0">
          {hasActiveFilters && (
            <button
              onClick={handleResetFilters}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-50 border border-rose-200 hover:bg-rose-100 text-rose-700 rounded-lg text-xs font-semibold transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Xóa bộ lọc
            </button>
          )}
          <button
            onClick={() => setIsFullscreen(!isFullscreen)}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-slate-800 hover:bg-slate-900 text-white rounded-lg text-xs font-semibold shadow-xs transition-all"
          >
            {isFullscreen ? (
              <>
                <Minimize2 className="w-4 h-4" /> Thu nhỏ
              </>
            ) : (
              <>
                <Maximize2 className="w-4 h-4" /> Toàn màn hình
              </>
            )}
          </button>
        </div>
      </div>

      {/* Conditionally render Full Dashboard widgets when not in single_chart view */}
      {!isSingleChart && (
        <>
          {/* 1. AI Data Storytelling Executive Insights Banner */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-xs space-y-3">
            <div className="flex items-center gap-2 font-bold text-xs text-brand-800 uppercase tracking-wider border-b border-slate-100 pb-2">
              <Lightbulb className="w-4 h-4 text-amber-500 animate-pulse" />
              <span>💡 Nhận Định Cốt Lõi AI — Executive Data Storytelling</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {storytellingInsights.map((insight, idx) => {
                const Icon = insight.icon;
                return (
                  <div
                    key={idx}
                    className={`bg-gradient-to-br ${insight.color} p-3.5 rounded-xl border shadow-2xs flex flex-col justify-between space-y-2`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-extrabold uppercase tracking-wide flex items-center gap-1.5">
                        <Icon className="w-3.5 h-3.5 shrink-0" />
                        {insight.phase}
                      </span>
                      <span className="text-[9px] font-bold px-2 py-0.5 rounded-full bg-white/80 border border-slate-200/60 shadow-2xs">
                        {insight.tag}
                      </span>
                    </div>
                    <p className="text-xs leading-relaxed font-medium pt-1">
                      {insight.text}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 2. Responsive 4-Column Grid: Always 4 Mandatory Executive KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 min-h-[100px]">
            {displayKpis.map((kpi: KPIItem, idx: number) => {
              const isPos = kpi.changeType === 'positive';
              const isNeg = kpi.changeType === 'negative';

              let Icon = Hash;
              let accentBorder = 'border-l-slate-600';

              const ktype = kpi.type || (kpi.icon === 'DollarSign' ? 'currency' : kpi.icon === 'Layers' || kpi.icon === 'Database' ? 'count' : kpi.icon === 'Award' || kpi.icon === 'Tag' ? 'category' : 'number');

              if (ktype === 'count') {
                Icon = Database;
                accentBorder = 'border-l-blue-600';
              } else if (ktype === 'currency') {
                Icon = DollarSign;
                accentBorder = 'border-l-emerald-600';
              } else if (ktype === 'category') {
                Icon = Tag;
                accentBorder = 'border-l-amber-600';
              } else {
                Icon = Hash;
                accentBorder = 'border-l-indigo-600';
              }

              return (
                <div
                  key={idx}
                  className={`bg-white p-4 rounded-xl border border-slate-200 border-l-4 ${accentBorder} shadow-2xs hover:shadow-sm transition-shadow flex flex-col justify-between space-y-2`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider truncate">
                      {kpi.title}
                    </span>
                    <div className="p-1.5 bg-slate-100 text-slate-600 rounded-lg shrink-0">
                      <Icon className="w-3.5 h-3.5" />
                    </div>
                  </div>

                  <div>
                    <p className="text-2xl font-extrabold text-slate-900 tracking-tight truncate">
                      {kpi.value}
                    </p>
                    <div className="flex items-center justify-between mt-1">
                      {kpi.change ? (
                        <span
                          className={`inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded-full ${isPos
                              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                              : isNeg
                                ? 'bg-rose-50 text-rose-700 border border-rose-200'
                                : 'bg-slate-100 text-slate-700'
                            }`}
                        >
                          {isPos && <TrendingUp className="w-2.5 h-2.5 mr-1" />}
                          {isNeg && <TrendingDown className="w-2.5 h-2.5 mr-1" />}
                          {!isPos && !isNeg && <Minus className="w-2.5 h-2.5 mr-1" />}
                          {kpi.change}
                        </span>
                      ) : (
                        <span className="text-[10px] text-slate-400">KPI Doanh nghiệp</span>
                      )}
                      {kpi.subtitle && (
                        <span className="text-[10px] text-slate-400 truncate">{kpi.subtitle}</span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Slicers Filter Bar */}
          {filterCategories.length > 0 && (
            <div className="w-full max-w-full bg-slate-50/80 border border-slate-200/80 rounded-2xl p-3 my-3 overflow-hidden">
              <div className="flex items-center gap-2 mb-2 text-xs font-bold text-slate-700">
                <Filter className="w-4 h-4 text-[#005697]" />
                <span>Bộ Lọc Slicers:</span>
              </div>

              <div className="flex flex-wrap items-center gap-2.5 w-full max-w-full overflow-hidden">
                {filterCategories.slice(0, 4).map((catKey) => {
                  const uniqueVals = Array.from(
                    new Set(rawRows.map((r) => String(r[catKey] ?? '')).filter(Boolean))
                  );

                  return (
                    <div
                      key={catKey}
                      className="flex items-center gap-1.5 bg-white border border-slate-200 rounded-xl px-2.5 py-1 text-xs shadow-xs max-w-[210px] shrink-0"
                    >
                      <span className="font-semibold text-slate-600 truncate max-w-[70px]" title={catKey}>
                        {catKey.replace(/_/g, ' ')}:
                      </span>
                      <select
                        value={selectedFilters[catKey]?.[0] || ''}
                        onChange={(e) => {
                          const val = e.target.value;
                          setSelectedFilters((prev) => ({
                            ...prev,
                            [catKey]: val ? [val] : [],
                          }));
                        }}
                        className="bg-transparent font-medium text-slate-800 focus:outline-none cursor-pointer truncate max-w-[120px] text-xs"
                      >
                        <option value="">-- Tất cả --</option>
                        {uniqueVals.slice(0, 30).map((v) => (
                          <option key={v} value={v} className="truncate">
                            {v}
                          </option>
                        ))}
                      </select>
                    </div>
                  );
                })}

                {hasActiveFilters && (
                  <button
                    onClick={handleResetFilters}
                    className="text-[11px] font-semibold text-rose-600 hover:text-rose-700 underline px-2 shrink-0"
                  >
                    Xóa bộ lọc
                  </button>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {/* ROW 2: Charts Area */}
      {isSingleChart ? (
        /* SINGLE CHART VIEW MODE: 1 Card Biểu đồ Trọng tâm occupying full width col-span-12 with height h-[480px] */
        <div className="col-span-12 bg-white p-5 rounded-2xl border border-slate-200 shadow-2xs hover:shadow-xs transition-shadow min-h-[520px] flex flex-col">
          <div className="flex items-center justify-between border-b border-slate-100 pb-3 mb-4">
            <span className="font-bold text-slate-800 text-sm flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-indigo-600" />
              {primaryChart?.title || 'Biểu Đồ Xu Hướng Trọng Tâm'}
            </span>
            <span className="text-xs px-2.5 py-1 bg-indigo-50 text-indigo-700 font-semibold rounded-full border border-indigo-200">
              Single Chart View
            </span>
          </div>
          {primaryChart ? (
            primaryChart.data && primaryChart.data.length > 0 ? (
              <EChartComponent chartSpec={primaryChart} height="480px" onChartClick={(params: any) => handleChartClick(params, primaryChart)} />
            ) : (
              <ReactECharts
                option={getDynamicChartOption(primaryChart, false)}
                style={{ height: '480px', width: '100%' }}
                onEvents={{ click: (params: any) => handleChartClick(params, primaryChart) }}
                notMerge={true}
                lazyUpdate={true}
              />
            )
          ) : (
            <div className="h-[480px] flex items-center justify-center text-xs text-slate-400 italic">Không có dữ liệu biểu đồ.</div>
          )}
        </div>
      ) : (
        /* FULL DASHBOARD VIEW MODE: (7 : 5 ratio) */
        <div className="grid grid-cols-12 gap-6 min-h-[380px]">
          {/* Left Primary Chart (col-span-7) */}
          <div className="col-span-12 lg:col-span-7 bg-white p-4 rounded-2xl border border-slate-200 shadow-2xs hover:shadow-xs transition-shadow min-h-[360px] flex flex-col">
            <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-3">
              <span className="font-bold text-slate-800 text-xs flex items-center gap-1.5">
                <BarChart3 className="w-4 h-4 text-indigo-600" /> Biểu Đồ Phân Tích Chính
              </span>
              <span className="text-[10px] text-slate-400 italic">Click vào cột để lọc chéo (Cross-filter)</span>
            </div>
            {primaryChart ? (
              primaryChart.data && primaryChart.data.length > 0 ? (
                <EChartComponent chartSpec={primaryChart} onChartClick={(params: any) => handleChartClick(params, primaryChart)} />
              ) : (
                <ReactECharts
                  option={getDynamicChartOption(primaryChart, false)}
                  style={{ height: '320px', width: '100%' }}
                  onEvents={{ click: (params: any) => handleChartClick(params, primaryChart) }}
                  notMerge={true}
                  lazyUpdate={true}
                />
              )
            ) : (
              <div className="h-[320px] flex items-center justify-center text-xs text-slate-400 italic">Không có dữ liệu biểu đồ.</div>
            )}
          </div>

          {/* Right Donut Chart (col-span-5) */}
          <div className="col-span-12 lg:col-span-5 bg-white p-4 rounded-2xl border border-slate-200 shadow-2xs hover:shadow-xs transition-shadow min-h-[360px] flex flex-col">
            <div className="flex items-center justify-between border-b border-slate-100 pb-2 mb-3">
              <span className="font-bold text-slate-800 text-xs flex items-center gap-1.5">
                <PieChartIcon className="w-4 h-4 text-teal-600" /> Tỷ Trọng & Thị Phần
              </span>
              <span className="text-[10px] text-slate-400 italic">Donut View</span>
            </div>
            {secondaryChart ? (
              secondaryChart.data && secondaryChart.data.length > 0 ? (
                <EChartComponent chartSpec={secondaryChart} isPie={true} onChartClick={(params: any) => handleChartClick(params, secondaryChart)} />
              ) : (
                <ReactECharts
                  option={getDynamicChartOption(secondaryChart, true)}
                  style={{ height: '320px', width: '100%' }}
                  onEvents={{ click: (params: any) => handleChartClick(params, secondaryChart) }}
                  notMerge={true}
                  lazyUpdate={true}
                />
              )
            ) : (
              <div className="h-[320px] flex items-center justify-center text-xs text-slate-400 italic">Không có dữ liệu biểu đồ.</div>
            )}
          </div>
        </div>
      )}

      {/* ROW 3: AG Grid Data Table (col-span-12) */}
      <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-100 pb-3">
          <div className="flex items-center space-x-2">
            <TableIcon className="w-4 h-4 text-brand-600" />
            <span className="font-bold text-slate-800 text-sm">
              {spec.table?.title || 'Bảng Chi Tiết Dữ Liệu'}
            </span>
            <span className="px-2.5 py-1 bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-md text-xs font-semibold">
              ( Hiển thị {filteredRows.length.toLocaleString()} / {(spec?.totalRows || rawRows.length).toLocaleString()} bản ghi )
            </span>
          </div>

          <div className="flex items-center space-x-2">
            {/* Quick Search Input */}
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
              <input
                type="text"
                placeholder="Tìm kiếm nhanh..."
                value={quickFilterText}
                onChange={(e) => setQuickFilterText(e.target.value)}
                className="pl-8 pr-3 py-1.5 bg-slate-50 border border-slate-300 rounded-lg text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-brand-500 w-44 sm:w-56"
              />
            </div>

            <button
              onClick={onExportCSV}
              className="flex items-center gap-1.5 px-3 py-1.5 border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold transition-colors"
            >
              <Download className="w-3.5 h-3.5 text-brand-600" /> CSV
            </button>

            <button
              onClick={onPrintReport}
              className="flex items-center gap-1.5 px-3 py-1.5 border border-slate-300 hover:bg-slate-50 text-slate-700 rounded-lg text-xs font-semibold transition-colors"
            >
              <Printer className="w-3.5 h-3.5 text-slate-600" /> In Báo Cáo
            </button>
          </div>
        </div>

        <div className="ag-theme-alpine w-full h-[580px] rounded-xl border border-slate-200">
          <AgGridReact
            ref={gridRef}
            rowData={filteredRows}
            columnDefs={columnDefs}
            pagination={true}
            paginationPageSize={20}
            paginationPageSizeSelector={[10, 20, 50, 100, 500]}
            quickFilterText={quickFilterText}
          />
        </div>
      </div>
    </div>
  );
};

function PieChartIcon(props: any) {
  return (
    <svg {...props} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M20.488 9H15V3.512A9.025 9.025 0 0120.488 9z" />
    </svg>
  );
}
