'use client';

import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { EChartComponent } from './EChartComponent';
import { AgGridReact } from 'ag-grid-react';
import { ColDef } from 'ag-grid-community';
import { DashboardSpec, ChartItem, KPIItem, TableColumn } from '../../lib/types';
import { useIsDark } from '../../lib/useIsDark';
import { formatMetricValue } from '../../lib/formatters';
import {
  Filter,
  BarChart3,
  PieChart,
  Table as TableIcon,
  Maximize2,
  Minimize2,
  Download,
  TrendingUp,
  TrendingDown,
  Minus,
  LayoutDashboard,
  RefreshCw,
  Search,
  SearchCheck,
  Printer,
  DollarSign,
  Lightbulb,
  Target,
  Database,
  Hash,
  Tag,
  X,
  RotateCcw,
} from 'lucide-react';

interface DynamicDashboardProps {
  spec: DashboardSpec;
}

export function stripEmojis(text: string): string {
  if (!text) return '';
  return text
    .replace(
      /[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{1F1E0}-\u{1F1FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F900}-\u{1F9FF}\u{1F018}-\u{1F270}\u{23FA}-\u{23FF}\u{2B05}-\u{2B07}\u{2B1B}\u{2B1C}\u{2B50}\u{2B55}\u{231A}\u{231B}\u{23E9}-\u{23EC}\u{23F0}\u{23F3}]/gu,
      ''
    )
    .replace(/\s+/g, ' ')
    .trim();
}

// Bước 1: Fuzzy Column Matcher an toàn, chống lệch hoa/thường, khoảng trắng, gạch dưới
export function getRowValue(row: Record<string, any>, targetCol: string): any {
  if (!row || !targetCol) return undefined;
  if (row[targetCol] !== undefined) return row[targetCol];

  const clean = (s: string) => String(s).toLowerCase().replace(/[\s_-]+/g, '');
  const normalizedTarget = clean(targetCol);

  // 1. Khớp chính xác sau chuẩn hóa
  const foundKey = Object.keys(row).find((key) => clean(key) === normalizedTarget);
  if (foundKey && row[foundKey] !== undefined) {
    return row[foundKey];
  }

  // 2. Khớp chuỗi con nếu cột là dạng gộp (e.g. "product category" <-> "product_category" <-> "category")
  const partialKey = Object.keys(row).find((key) => {
    const kClean = clean(key);
    return kClean.includes(normalizedTarget) || normalizedTarget.includes(kClean);
  });
  if (partialKey && row[partialKey] !== undefined) {
    return row[partialKey];
  }

  return undefined;
}

// Bước 2: Kiểm tra trạng thái bộ lọc có đang active hay không
export const isFilterActive = (val: any): boolean => {
  if (val === undefined || val === null) return false;
  const s = String(val).trim().toLowerCase();
  return (
    s !== '' &&
    s !== '-- tất cả --' &&
    s !== '-- tat ca --' &&
    s !== 'all' &&
    s !== 'tất cả' &&
    s !== 'tat ca' &&
    s !== 'undefined' &&
    s !== 'null'
  );
};

// Helper: Tìm cột tương ứng trong sampleRow
function findMatchingRowColumn(
  targetKey: string | undefined,
  sampleRow: Record<string, any>,
  fallbackCol?: string
): string {
  if (!targetKey && fallbackCol) return fallbackCol;
  if (!targetKey) return Object.keys(sampleRow)[0] || 'category';

  if (targetKey in sampleRow) return targetKey;

  const clean = (s: string) => String(s).toLowerCase().replace(/[\s_-]+/g, '');
  const cleanTarget = clean(targetKey);
  const found = Object.keys(sampleRow).find((k) => clean(k) === cleanTarget);
  if (found) return found;

  // Generic placeholders must NEVER undergo partial substring matching
  const genericKeys = ['x', 'y', 'val', 'val1', 'value', 'name', 'label', 'series', 'data', 'count', 'item'];
  if (!genericKeys.includes(cleanTarget) && cleanTarget.length >= 3) {
    const partial = Object.keys(sampleRow).find((k) => {
      const kc = clean(k);
      return kc.includes(cleanTarget) || cleanTarget.includes(kc);
    });
    if (partial) return partial;
  }

  return fallbackCol || targetKey;
}

// Helper: Extract numeric value safely from numbers or formatted strings ("$2,500.00", "1,500")
export const parseNumericValue = (val: any): number => {
  if (typeof val === 'number') return isNaN(val) ? 0 : val;
  if (!val) return 0;
  const cleaned = String(val).replace(/[^0-9.-]+/g, '');
  const num = parseFloat(cleaned);
  return isNaN(num) ? 0 : num;
};

// Helper to detect ID / Key columns
const isIdColumn = (colName: string, uniqueRatio: number) => {
  const k = colName.toLowerCase();
  const isKeyword =
    k === 'id' ||
    k === '_id' ||
    k === 'index' ||
    k.includes('id_') ||
    k.endsWith('_id') ||
    k.includes('code') ||
    k.includes('zip') ||
    k.includes('phone') ||
    k.includes('ssn') ||
    k.endsWith('_num') ||
    k.endsWith('number') ||
    k === 'order_id' ||
    k === 'customer_id';
  return isKeyword || uniqueRatio >= 0.95;
};

// Aggregation chuẩn cho Bar Chart: Group By + Continuous Metric Sum (không fallback 1.0)
function aggregateBarData(
  rows: any[],
  categoryCol: string,
  valueCol: string,
  topN = 0 // 0 = Giữ toàn bộ bản ghi cho ECharts dataZoom slider cuộn mượt
): { categories: string[]; values: number[] } {
  if (!rows || rows.length === 0) return { categories: [], values: [] };

  const sample = rows[0] || {};
  let effectiveValCol = valueCol;

  // Nếu valueCol là placeholder vô nghĩa ('y', 'value') hoặc không tồn tại, tự động tìm cột đo lường liên tục
  const isGeneric = ['x', 'y', 'value', 'val', 'val1', 'count', 'series', 'data'].includes(
    String(effectiveValCol || '').trim().toLowerCase()
  );
  if (isGeneric || !(effectiveValCol in sample)) {
    const numericCols = Object.keys(sample).filter((k) => {
      if (isIdColumn(k, 0)) return false;
      const v = sample[k];
      return typeof v === 'number' || (!isNaN(parseNumericValue(v)) && parseNumericValue(v) !== 0);
    });
    if (numericCols.length > 0) {
      numericCols.sort((a, b) => {
        const sumA = rows.slice(0, 50).reduce((acc, r) => acc + Math.abs(parseNumericValue(getRowValue(r, a))), 0);
        const sumB = rows.slice(0, 50).reduce((acc, r) => acc + Math.abs(parseNumericValue(getRowValue(r, b))), 0);
        return sumB - sumA;
      });
      effectiveValCol = numericCols[0];
    }
  }

  const map = new Map<string, number>();
  for (const row of rows) {
    const rawKey = getRowValue(row, categoryCol);
    const key = String(rawKey ?? '').trim();
    if (!key || key === 'undefined' || key === 'null' || key === 'N/A') continue;

    const rawVal = getRowValue(row, effectiveValCol);
    // Đo lường liên tục chuẩn xác, tuyệt đối KHÔNG fallback về 1.0
    const num = typeof rawVal === 'number' ? (isNaN(rawVal) ? 0 : rawVal) : parseNumericValue(rawVal);

    map.set(key, (map.get(key) || 0) + (isNaN(num) ? 0 : num));
  }

  // Sắp xếp giảm dần theo chỉ số đo lường
  const sorted = Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
  const finalItems = topN > 0 ? sorted.slice(0, topN) : sorted;

  return {
    categories: finalItems.map(([k]) => k),
    values: finalItems.map(([, v]) => v),
  };
}

// Aggregation chuẩn cho Donut Chart: Phân bố tỷ trọng trên toàn bộ bản ghi (500 dòng)
function aggregatePieData(
  rows: any[],
  categoryCol: string,
  valueCol?: string,
  maxSlices = 6
): { name: string; value: number }[] {
  if (!rows || rows.length === 0) return [];

  const sample = rows[0] || {};
  const isGenericVal =
    !valueCol ||
    ['x', 'y', 'value', 'val', 'val1', 'count', 'data'].includes(String(valueCol).trim().toLowerCase());

  // Kiểm tra xem valueCol có phải là một cột số đo thực sự hay là phân loại tỷ trọng số lượng
  const hasRealNumericVal =
    !isGenericVal &&
    valueCol in sample &&
    (typeof sample[valueCol] === 'number' || !isNaN(parseNumericValue(sample[valueCol])));

  const map = new Map<string, number>();
  for (const row of rows) {
    const rawKey = getRowValue(row, categoryCol);
    const key = String(rawKey ?? '').trim();
    if (!key || key === 'undefined' || key === 'null' || key === 'N/A') continue;

    if (hasRealNumericVal && valueCol) {
      const rawVal = getRowValue(row, valueCol);
      const num = parseNumericValue(rawVal);
      const safeNum = isNaN(num) ? 0 : Number(num);
      map.set(key, Number(map.get(key) || 0) + safeNum);
    } else {
      // Đếm tần suất (count(*)) chuẩn xác trên toàn bộ bản ghi
      map.set(key, Number(map.get(key) || 0) + 1);
    }
  }

  const total = Array.from(map.values()).reduce((a, b) => Number(a) + Number(b), 0);
  if (total === 0 || map.size === 0) return [];

  // Sort descending
  const sorted = Array.from(map.entries()).sort((a, b) => Number(b[1]) - Number(a[1]));

  // Gom nhóm "Khác" chỉ nếu có nhiều hơn maxSlices (6) phân loại
  if (sorted.length <= maxSlices) {
    return sorted.map(([name, value]) => ({
      name,
      value: Number.isInteger(value) ? value : Math.round(Number(value) * 100) / 100,
    }));
  }

  const topItems = sorted.slice(0, maxSlices - 1);
  const otherItems = sorted.slice(maxSlices - 1);
  const otherSum = otherItems.reduce((acc, [, val]) => Number(acc) + Number(val), 0);

  const result = topItems.map(([name, value]) => ({
    name,
    value: Number.isInteger(value) ? value : Math.round(Number(value) * 100) / 100,
  }));
  if (otherSum > 0) {
    result.push({
      name: 'Khác',
      value: Number.isInteger(otherSum) ? otherSum : Math.round(Number(otherSum) * 100) / 100,
    });
  }

  return result;
}

export const DynamicDashboard: React.FC<DynamicDashboardProps> = ({ spec }) => {
  const isDark = useIsDark();
  const [isMounted, setIsMounted] = useState(false);

  const [isFullscreen, setIsFullscreen] = useState(false);
  const [activeFilters, setActiveFilters] = useState<Record<string, string>>({});
  const [quickFilterText, setQuickFilterText] = useState('');
  const gridRef = useRef<AgGridReact>(null);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  // Extract raw data rows from spec.table or multiple fallback candidate keys
  const rawRows = useMemo(() => {
    if (spec?.table?.rows && Array.isArray(spec.table.rows) && spec.table.rows.length > 0) {
      return spec.table.rows;
    }
    if ((spec as any)?.raw_data && Array.isArray((spec as any).raw_data) && (spec as any).raw_data.length > 0) {
      return (spec as any).raw_data;
    }
    if ((spec as any)?.rawData && Array.isArray((spec as any).rawData) && (spec as any).rawData.length > 0) {
      return (spec as any).rawData;
    }
    if ((spec as any)?.rawRows && Array.isArray((spec as any).rawRows) && (spec as any).rawRows.length > 0) {
      return (spec as any).rawRows;
    }
    if ((spec as any)?.rows && Array.isArray((spec as any).rows) && (spec as any).rows.length > 0) {
      return (spec as any).rows;
    }
    return [];
  }, [spec]);

  // Client-side row filtering with safe Filter Normalization
  const filteredRows = useMemo(() => {
    if (!rawRows || !Array.isArray(rawRows) || rawRows.length === 0) return [];

    const activeEntries = Object.entries(activeFilters).filter(([_, val]) => isFilterActive(val));
    if (activeEntries.length === 0) return rawRows; // Giữ nguyên 100% dữ liệu khi chưa lọc

    return rawRows.filter((row) => {
      return activeEntries.every(([filterKey, filterVal]) => {
        const cellValue = getRowValue(row, filterKey);
        if (cellValue === undefined || cellValue === null) return false;
        return String(cellValue).trim().toLowerCase() === String(filterVal).trim().toLowerCase();
      });
    });
  }, [rawRows, activeFilters]);

  // Debug log data counts
  useEffect(() => {
    console.log('[Dashboard Debug] rawRows count:', rawRows?.length, 'filteredRows count:', filteredRows?.length);
  }, [rawRows?.length, filteredRows?.length]);

  // Identify slicers (Categorical non-ID columns with 2 to 20 unique values, maximum 4 slicers)
  const filterCategories = useMemo(() => {
    const explicitSlicers = (spec as any)?.slicers || (spec as any)?.filter_columns || [];
    if (Array.isArray(explicitSlicers) && explicitSlicers.length > 0) {
      return explicitSlicers.filter((s: string) => typeof s === 'string').slice(0, 4);
    }

    const categoryCols = (spec as any)?.valid_category_cols || (spec as any)?.validCategoryCols || (spec as any)?.donut_pie_cat_cols || [];
    let candidates: string[] = [];

    if (Array.isArray(categoryCols) && categoryCols.length > 0) {
      candidates = categoryCols.filter((col: string) => {
        const uniqueVals = new Set((rawRows || []).map((r: Record<string, any>) => String(getRowValue(r, col) ?? '')));
        return uniqueVals.size >= 2 && uniqueVals.size <= 20;
      });
    }

    if (candidates.length === 0 && rawRows.length > 0) {
      const keys = Object.keys(rawRows[0] || {});
      const totalCount = rawRows.length;

      candidates = keys.filter((key) => {
        const sampleVal = rawRows[0][key];
        if (typeof sampleVal === 'number' && !isNaN(Number(sampleVal))) return false;

        const uniqueVals = new Set(rawRows.map((r: Record<string, any>) => String(getRowValue(r, key) ?? '')));
        const uniqueCount = uniqueVals.size;
        const uniqueRatio = totalCount > 0 ? uniqueCount / totalCount : 0;

        if (isIdColumn(key, uniqueRatio)) return false;

        return uniqueCount >= 2 && uniqueCount <= 20;
      });
    }

    return candidates.slice(0, 4);
  }, [rawRows, spec]);

  // Centralized filter change handler
  const handleFilterChange = useCallback((column: string, value: string | null) => {
    setActiveFilters((prev) => {
      const updated = { ...prev };
      if (!isFilterActive(value)) {
        delete updated[column];
      } else {
        updated[column] = String(value).trim();
      }
      return updated;
    });
  }, []);

  // Reset all filters
  const handleResetFilters = useCallback(() => {
    setActiveFilters({});
    setQuickFilterText('');
  }, []);

  // Render strictly valid KPI Cards without padding dummy cards ("THỐNG KÊ 4")
  const displayKpis = useMemo(() => {
    const rawKpis: KPIItem[] = spec?.kpis && spec.kpis.length > 0 ? spec.kpis : (spec as any)?.kpiCards || [];
    return rawKpis.filter((kpi) => {
      const title = (kpi?.title || '').toUpperCase();
      return !title.includes('THỐNG KÊ 4') && !title.includes('KPI 4') && !title.includes('FALLBACK');
    });
  }, [spec?.kpis, (spec as any)?.kpiCards]);

  // Dynamically recalculated KPI Cards according to filteredRows
  const dynamicKpis = useMemo(() => {
    const isFiltered = Object.keys(activeFilters).some((k) => isFilterActive(activeFilters[k]));
    return displayKpis.map((kpi) => {
      if (!isFiltered) return kpi;

      const ktype = kpi.type || (kpi.icon === 'Layers' || kpi.icon === 'Database' ? 'count' : '');
      const titleUpper = (kpi.title || '').toUpperCase();

      // 1. Thẻ đếm số lượng / bản ghi
      if (
        ktype === 'count' ||
        titleUpper.includes('TỔNG BẢN GHI') ||
        titleUpper.includes('TOTAL ROWS') ||
        titleUpper.includes('RECORDS') ||
        titleUpper.includes('BẢN GHI')
      ) {
        return {
          ...kpi,
          value: filteredRows.length.toLocaleString(),
          subtitle: `Đã lọc từ ${rawRows.length.toLocaleString()} bản ghi gốc`,
        };
      }

      // 2. Thẻ số liệu / measure nghiệp vụ
      if (filteredRows.length > 0 && rawRows.length > 0) {
        const sample = filteredRows[0] || {};
        const matchedCol = Object.keys(sample).find((k) => {
          const lk = k.toLowerCase().replace(/_/g, ' ');
          const lt = (kpi.title || '').toLowerCase().replace(/_/g, ' ');
          return lt.includes(lk) || lk.includes(lt);
        });

        if (matchedCol && !isIdColumn(matchedCol, 0)) {
          const sumVal = filteredRows.reduce((acc, r) => acc + parseNumericValue(getRowValue(r, matchedCol)), 0);
          return {
            ...kpi,
            value: formatMetricValue(sumVal, matchedCol, kpi.unit),
            subtitle: `Đã lọc (${filteredRows.length.toLocaleString()} dòng)`,
          };
        }

        // 3. Proportional scaling fallback cho các chỉ số khác
        const ratio = filteredRows.length / rawRows.length;
        const origNum = parseNumericValue(kpi.value);
        if (origNum > 0) {
          const scaled = origNum * ratio;
          return {
            ...kpi,
            value: formatMetricValue(scaled, kpi.title, kpi.unit),
            subtitle: `Đã lọc (${Math.round(ratio * 100)}%)`,
          };
        }
      }

      return kpi;
    });
  }, [displayKpis, filteredRows, rawRows, activeFilters]);

  // Structured Data Storytelling AI Insights (Diễn Biến -> Nguyên Nhân -> Khuyến Nghị)
  const storytellingInsights = useMemo(() => {
    let dienBien = '';
    let nguyenNhan = '';
    let khuyenNghi = '';

    const summaryText: string = String(spec?.summaryText || spec?.summary || '');
    if (summaryText) {
      const cleanSummary = stripEmojis(summaryText);
      const dienBienMatch = cleanSummary.match(/Diễn biến[:\s]*([\s\S]*?)(?=Nguyên nhân|Khuyến nghị|$)/i) || summaryText.match(/(?:\uD83D\uDCC8|Diễn biến[:\s]*)([^\uD83D\uDD0D\uD83C\uDFAF\n]*)/i);
      const nguyenNhanMatch = cleanSummary.match(/Nguyên nhân[:\s]*([\s\S]*?)(?=Khuyến nghị|Diễn biến|$)/i) || summaryText.match(/(?:\uD83D\uDD0D|Nguyên nhân[:\s]*)([^\uD83C\uDFAF\uD83D\uDCC8\n]*)/i);
      const khuyenNghiMatch = cleanSummary.match(/Khuyến nghị[:\s]*([\s\S]*?)(?=Diễn biến|Nguyên nhân|$)/i) || summaryText.match(/(?:\uD83C\uDFAF|Khuyến nghị[:\s]*)([^\uD83D\uDCC8\uD83D\uDD0D\n]*)/i);

      if (dienBienMatch && dienBienMatch[1].trim()) dienBien = stripEmojis(dienBienMatch[1].trim());
      if (nguyenNhanMatch && nguyenNhanMatch[1].trim()) nguyenNhan = stripEmojis(nguyenNhanMatch[1].trim());
      if (khuyenNghiMatch && khuyenNghiMatch[1].trim()) khuyenNghi = stripEmojis(khuyenNghiMatch[1].trim());

      if (!dienBien || !nguyenNhan || !khuyenNghi) {
        const sentences = cleanSummary.split('.').map((s: string) => s.trim()).filter((s: string) => s.length > 5);
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
      rawRows.forEach((r: Record<string, any>) => {
        const val = String(getRowValue(r, catCol) ?? 'Khác');
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
        phase: 'DIỄN BIẾN',
        tag: 'Bức tranh toàn cảnh',
        theme: {
          iconBg: 'bg-accent-primary/10',
          iconColor: 'text-accent-primary',
        },
        icon: TrendingUp,
        text: stripEmojis(dienBien),
      },
      {
        phase: 'NGUYÊN NHÂN',
        tag: 'Động lực chính',
        theme: {
          iconBg: 'bg-accent-planner/10',
          iconColor: 'text-accent-planner',
        },
        icon: SearchCheck,
        text: stripEmojis(nguyenNhan),
      },
      {
        phase: 'KHUYẾN NGHỊ',
        tag: 'Hành động chiến lược',
        theme: {
          iconBg: 'bg-accent-verifier/10',
          iconColor: 'text-accent-verifier',
        },
        icon: Lightbulb,
        text: stripEmojis(khuyenNghi),
      },
    ];
  }, [spec.summary, spec.summaryText, rawRows, filterCategories]);

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

  // Helper to resolve Dimension and Metric Columns of a chart with Cardinality Awareness
  const getChartDimCol = useCallback(
    (chart?: ChartItem, isPie = false, fallbackIndex = 0): string => {
      const sample = rawRows[0] || {};
      const keys = Object.keys(sample);
      if (keys.length === 0) return 'category';

      const direct = chart?.x_axis_key || (chart as any)?.xAxisKey || chart?.name_key || (chart as any)?.dimension;
      let directCol: string | undefined = undefined;
      if (direct) {
        const found = findMatchingRowColumn(direct, sample);
        if (found && !isIdColumn(found, 0)) directCol = found;
      }

      // Helper to compute unique values count in rawRows for a column
      const getColCardinality = (col: string): number => {
        const set = new Set(rawRows.map((r: Record<string, any>) => String(getRowValue(r, col) ?? '')));
        return set.size;
      };

      if (isPie) {
        // QUY TẮC A: Donut/Pie Chart MUST use low-cardinality categorical column (2 <= nunique <= 7)
        if (directCol) {
          const card = getColCardinality(directCol);
          if (card >= 2 && card <= 7) return directCol;
        }

        // Find candidate with 2 <= nunique <= 7
        const validDonutCol = keys.find((k) => {
          if (isIdColumn(k, 0)) return false;
          const sampleVal = sample[k];
          if (typeof sampleVal === 'number' && !isNaN(Number(sampleVal))) return false;
          const card = getColCardinality(k);
          return card >= 2 && card <= 7;
        });
        if (validDonutCol) return validDonutCol;

        if (filterCategories.length > 0) return filterCategories[0];
      } else {
        // QUY TẮC B: Bar Chart (Main Analysis) MUST select primary entity column with high cardinality (Top 10-15)
        if (directCol) {
          const card = getColCardinality(directCol);
          const hasBetterEntity = keys.some((k) => {
            if (isIdColumn(k, 0)) return false;
            const sampleVal = sample[k];
            return typeof sampleVal === 'string' && getColCardinality(k) >= 5;
          });
          if (card > 3 || !hasBetterEntity) return directCol;
        }

        // Find candidate non-ID string column with nunique >= 5, sorted descending by cardinality
        const stringCols = keys
          .filter((k) => {
            if (isIdColumn(k, 0)) return false;
            const sampleVal = sample[k];
            return typeof sampleVal === 'string' && isNaN(Number(sampleVal)) && getColCardinality(k) >= 5;
          })
          .sort((a, b) => getColCardinality(b) - getColCardinality(a));

        if (stringCols.length > 0) return stringCols[0];
      }

      if (directCol) return directCol;
      if (filterCategories.length > fallbackIndex) {
        return filterCategories[fallbackIndex];
      }

      return keys[0] || 'category';
    },
    [rawRows, filterCategories]
  );

  const getChartMetricCol = useCallback(
    (chart?: ChartItem): string => {
      const sample = rawRows[0] || {};
      const keys = Object.keys(sample);
      if (keys.length === 0) return 'value';

      const genericKeys = ['x', 'y', 'value', 'val', 'val1', 'count', 'data', 'series'];

      // 1. Kiểm tra các trường chỉ định metric / measure từ chart spec
      const explicitCandidates = [
        (chart as any)?.metric,
        (chart as any)?.measure,
        (chart as any)?.measure_col,
        (chart as any)?.y_axis_metric,
        chart?.y_axis_key,
        (chart as any)?.yAxisKey,
        chart?.value_key,
        chart?.series_keys?.[0],
      ].filter(Boolean);

      for (const cand of explicitCandidates) {
        if (typeof cand !== 'string') continue;
        const candTrim = cand.trim();
        if (candTrim in sample && !genericKeys.includes(candTrim.toLowerCase())) {
          const sampleVal = sample[candTrim];
          if (typeof sampleVal === 'number' || (!isNaN(parseNumericValue(sampleVal)) && parseNumericValue(sampleVal) !== 0)) {
            return candTrim;
          }
        }
        if (!genericKeys.includes(candTrim.toLowerCase()) && candTrim.length >= 3) {
          const found = findMatchingRowColumn(candTrim, sample);
          if (found && found in sample && !isIdColumn(found, 0)) {
            const sampleVal = sample[found];
            if (typeof sampleVal === 'number' || (!isNaN(parseNumericValue(sampleVal)) && parseNumericValue(sampleVal) !== 0)) {
              return found;
            }
          }
        }
      }

      // 2. Continuous numeric metrics excluding percentages/ratios/IDs
      const numericCandidates = keys
        .filter((k) => {
          if (isIdColumn(k, 0)) return false;
          const lk = k.toLowerCase();
          if (lk.includes('%') || lk.includes('percent') || lk.includes('ratio') || lk.includes('rate') || lk.includes('pct')) {
            return false;
          }
          const v = parseNumericValue(sample[k]);
          return !isNaN(v) && v !== 0;
        })
        .sort((a, b) => {
          // Sắp xếp theo độ lớn tổng giá trị trên 100 dòng đầu
          const sumA = rawRows.slice(0, 100).reduce((acc: number, r: Record<string, any>) => acc + Math.abs(parseNumericValue(getRowValue(r, a))), 0);
          const sumB = rawRows.slice(0, 100).reduce((acc: number, r: Record<string, any>) => acc + Math.abs(parseNumericValue(getRowValue(r, b))), 0);
          return sumB - sumA;
        });

      if (numericCandidates.length > 0) {
        return numericCandidates[0];
      }

      // 3. Fallback to any numeric column
      const anyNum = keys.find((k) => !isIdColumn(k, 0) && !isNaN(parseNumericValue(sample[k])));
      return anyNum || 'value';
    },
    [rawRows]
  );

  // Cross-filtering click handler on charts with robust toggle & delete cleanup
  const handleChartCrossFilter = useCallback((dimensionCol: string, clickedValue: string) => {
    if (!dimensionCol || !clickedValue) return;

    const cleanVal = String(clickedValue).trim();
    if (
      !cleanVal ||
      cleanVal === 'Không có dữ liệu' ||
      cleanVal === 'No data' ||
      cleanVal === 'Khác'
    ) {
      return;
    }

    setActiveFilters((prev) => {
      const updated = { ...prev };
      const currentVal = updated[dimensionCol];

      // So sánh an toàn không phân biệt hoa thường và khoảng trắng
      const isSameValue =
        currentVal &&
        String(currentVal).trim().toLowerCase() === cleanVal.toLowerCase();

      if (isSameValue) {
        // HỦY LỌC: Xóa hoàn toàn key khỏi object để state trở về sạch sẽ
        delete updated[dimensionCol];
      } else {
        // CHỌN LỌC MỚI: Gán giá trị lọc chuẩn xác
        updated[dimensionCol] = cleanVal;
      }
      return updated;
    });
  }, []);

  // Smart slot matching: Primary slot gets Bar/Ranking chart, Secondary slot gets Donut/Pie
  const primaryChart = useMemo(() => {
    if (!spec.charts || spec.charts.length === 0) return undefined;
    const bar = spec.charts.find((c) => {
      const t = (c.type || '').toLowerCase();
      return t === 'bar' || t === 'ranking_bar' || t === 'line';
    });
    return bar || spec.charts[0];
  }, [spec.charts]);

  const secondaryChart = useMemo(() => {
    if (!spec.charts || spec.charts.length === 0) return undefined;
    const pie = spec.charts.find((c) => {
      const t = (c.type || '').toLowerCase();
      return t === 'pie' || t === 'donut';
    });
    return pie || (spec.charts.length > 1 ? spec.charts[1] : spec.charts[0]);
  }, [spec.charts]);

  const primaryDimCol = useMemo(() => getChartDimCol(primaryChart, false, 0), [getChartDimCol, primaryChart]);
  const primaryMetricCol = useMemo(() => getChartMetricCol(primaryChart), [getChartMetricCol, primaryChart]);

  const secondaryDimCol = useMemo(() => getChartDimCol(secondaryChart, true, 1), [getChartDimCol, secondaryChart]);
  const secondaryMetricCol = useMemo(() => getChartMetricCol(secondaryChart), [getChartMetricCol, secondaryChart]);

  // Selected values for charts
  const primarySelected = activeFilters[primaryDimCol] || null;
  const secondarySelected = activeFilters[secondaryDimCol] || null;

  // Rows to aggregate for primary chart: filtered by all active filters EXCEPT primaryDimCol
  const primaryRowsToAggregate = useMemo(() => {
    if (!rawRows || rawRows.length === 0) return [];
    const otherActiveFilters = Object.entries(activeFilters).filter(([col, val]) => {
      if (!isFilterActive(val)) return false;
      const cleanCol = col.toLowerCase().replace(/[\s_-]+/g, '');
      const cleanDim = primaryDimCol.toLowerCase().replace(/[\s_-]+/g, '');
      return cleanCol !== cleanDim;
    });

    if (otherActiveFilters.length === 0) return rawRows;

    return rawRows.filter((row: Record<string, any>) => {
      return otherActiveFilters.every(([col, val]) => {
        const cellValue = getRowValue(row, col);
        if (cellValue === undefined || cellValue === null) return false;
        return String(cellValue).trim().toLowerCase() === String(val).trim().toLowerCase();
      });
    });
  }, [rawRows, activeFilters, primaryDimCol]);

  // Rows to aggregate for secondary chart: filtered by all active filters EXCEPT secondaryDimCol
  const secondaryRowsToAggregate = useMemo(() => {
    if (!rawRows || rawRows.length === 0) return [];
    const otherActiveFilters = Object.entries(activeFilters).filter(([col, val]) => {
      if (!isFilterActive(val)) return false;
      const cleanCol = col.toLowerCase().replace(/[\s_-]+/g, '');
      const cleanDim = secondaryDimCol.toLowerCase().replace(/[\s_-]+/g, '');
      return cleanCol !== cleanDim;
    });

    if (otherActiveFilters.length === 0) return rawRows;

    return rawRows.filter((row: Record<string, any>) => {
      return otherActiveFilters.every(([col, val]) => {
        const cellValue = getRowValue(row, col);
        if (cellValue === undefined || cellValue === null) return false;
        return String(cellValue).trim().toLowerCase() === String(val).trim().toLowerCase();
      });
    });
  }, [rawRows, activeFilters, secondaryDimCol]);

  // Computed Primary Chart with Top 12 Aggregation and Backend Spec Fallback
  const computedPrimaryChart = useMemo(() => {
    if (!primaryChart) return null;

    // 1. Try dynamic aggregation if rows are available
    if (primaryRowsToAggregate && primaryRowsToAggregate.length > 0) {
      const { categories, values } = aggregateBarData(
        primaryRowsToAggregate,
        primaryDimCol,
        primaryMetricCol,
        0 // 0 = Giữ toàn bộ bản ghi cho ECharts dataZoom slider
      );

      if (categories.length > 0) {
        const data = categories.map((cat, idx) => ({
          [primaryDimCol]: cat,
          name: cat,
          [primaryMetricCol]: values[idx],
          value: values[idx],
        }));

        return {
          ...primaryChart,
          x_axis_key: primaryDimCol,
          series_keys: [primaryMetricCol],
          x_data: categories,
          data,
        };
      }
    }

    // 2. Smart Fallback to backend initial spec chart data
    if (primaryChart.data && Array.isArray(primaryChart.data) && primaryChart.data.length > 0) {
      return primaryChart;
    }

    return primaryChart;
  }, [primaryChart, primaryRowsToAggregate, primaryDimCol, primaryMetricCol]);

  // Computed Secondary Chart (Pie/Donut) with Safe Slices and Backend Spec Fallback
  const computedSecondaryChart = useMemo(() => {
    if (!secondaryChart) return null;

    const sample = rawRows[0] || {};
    const isGenericVal =
      !secondaryMetricCol ||
      ['x', 'y', 'value', 'val', 'val1', 'count', 'data'].includes(String(secondaryMetricCol).trim().toLowerCase());
    const hasRealNumericVal =
      !isGenericVal &&
      secondaryMetricCol in sample &&
      (typeof sample[secondaryMetricCol] === 'number' || !isNaN(parseNumericValue(sample[secondaryMetricCol])));

    const aggType: 'SUM' | 'COUNT' = hasRealNumericVal ? 'SUM' : 'COUNT';
    const measureName = hasRealNumericVal ? secondaryMetricCol : 'count';
    const dynamicSubtitle = hasRealNumericVal
      ? `Theo ${secondaryDimCol} • Đo lường: Tổng ${secondaryMetricCol} (Hàm: SUM)`
      : `Theo ${secondaryDimCol} • Đo lường: Số lượng đơn hàng (Số dòng) (Hàm: COUNT)`;

    // 1. Try dynamic aggregation if rows are available
    if (secondaryRowsToAggregate && secondaryRowsToAggregate.length > 0) {
      const pieData = aggregatePieData(
        secondaryRowsToAggregate,
        secondaryDimCol,
        hasRealNumericVal ? secondaryMetricCol : undefined,
        6 // Max 6 slices
      );

      if (pieData.length > 0) {
        return {
          ...secondaryChart,
          type: 'pie' as const,
          title: secondaryChart.title || 'Tỷ Trọng & Thị Phần',
          subtitle: secondaryChart.subtitle || dynamicSubtitle,
          dimension: secondaryDimCol,
          measure: measureName,
          aggregation: aggType,
          name_key: secondaryDimCol,
          value_key: hasRealNumericVal ? secondaryMetricCol : 'value',
          data: pieData,
        };
      }
    }

    // 2. Smart Fallback to backend initial spec chart data
    if (secondaryChart.data && Array.isArray(secondaryChart.data) && secondaryChart.data.length > 0) {
      return {
        ...secondaryChart,
        dimension: secondaryChart.dimension || secondaryDimCol,
        measure: secondaryChart.measure || measureName,
        aggregation: secondaryChart.aggregation || aggType,
        subtitle: secondaryChart.subtitle || dynamicSubtitle,
      };
    }

    return secondaryChart;
  }, [secondaryChart, secondaryRowsToAggregate, secondaryDimCol, secondaryMetricCol, rawRows]);

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
            return formatMetricValue(params.value, col.field);
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
        valueFormatter: (params: any) => {
          if (typeof params.value === 'number') {
            return formatMetricValue(params.value, key);
          }
          return params.value;
        },
      }));
    }

    return [];
  }, [spec.table, rawRows]);

  const displayTotalRows = spec?.totalRows ?? spec?.total_rows ?? spec?.total_records ?? rawRows.length ?? 0;
  const displayTotalCols = spec?.totalColumns ?? spec?.total_cols ?? spec?.total_fields ?? 0;

  const hasActiveFilters =
    Object.keys(activeFilters).some((k) => isFilterActive(activeFilters[k])) ||
    quickFilterText.trim().length > 0;

  const isSingleChart =
    spec?.layout_type === 'single_chart' ||
    (spec as any)?.layout?.layout_type === 'single_chart' ||
    (spec?.charts?.length === 1 && (!displayKpis || displayKpis.length === 0));

  if (!isMounted) {
    return (
      <div className="min-h-[500px] w-full animate-pulse bg-surface/90 rounded-2xl border border-border my-4" />
    );
  }

  return (
    <div
      data-testid="dashboard-container"
      className={`transition-all duration-300 dynamic-dashboard-container ${
        isFullscreen
          ? 'fixed top-0 right-0 bottom-0 z-40 overflow-y-auto bg-surface p-6 shadow-2xl'
          : 'w-full space-y-6 my-4 bg-surface/90 p-5 rounded-2xl border border-border shadow-sm min-h-[500px]'
      }`}
      style={isFullscreen ? { left: 'var(--sidebar-width, 4rem)' } : undefined}
    >
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border pb-4">
        <div className="flex items-center space-x-3">
          <div className="p-2.5 bg-accent-primary text-white rounded-xl shadow-xs">
            <LayoutDashboard className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-xl font-extrabold text-foreground tracking-tight flex items-center gap-2">
              {spec?.datasetName
                ? `${spec.datasetName.replace(/\.[^/.]+$/, '').toUpperCase()} ${isSingleChart ? 'Chart View' : 'Analytics Dashboard'}`
                : spec?.dashboard_title || 'Dataset Analytics View'}
            </h2>
            <p className="text-xs text-foreground-secondary mt-0.5 font-mono tabular-nums">
              {displayTotalRows > 0
                ? `Phân tích tự động dựa trên ${displayTotalRows.toLocaleString()} dòng dữ liệu và ${displayTotalCols > 0 ? displayTotalCols.toLocaleString() : '--'} trường.`
                : 'Hệ thống Multi-Agent BI • Phân tích real-time & tương tác chéo'}
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2 shrink-0">
          {hasActiveFilters && (
            <button
              type="button"
              onClick={handleResetFilters}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-accent-error/10 border border-accent-error/20 hover:bg-accent-error/20 text-accent-error rounded-lg text-xs font-semibold transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-error/40"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Xóa bộ lọc
            </button>
          )}
          <button
            type="button"
            onClick={() => setIsFullscreen(!isFullscreen)}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-surface-raised hover:bg-surface-overlay text-foreground border border-border rounded-lg text-xs font-semibold shadow-xs transition-all cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
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
          <div className="bg-surface border border-border rounded-2xl p-4 shadow-xs space-y-3">
            <div className="flex items-center gap-2 font-bold text-xs text-accent-primary uppercase tracking-wider border-b border-border pb-2">
              <Lightbulb className="w-4 h-4 text-accent-primary animate-pulse" />
              <span>Nhận Định Cốt Lõi AI — Executive Data Storytelling</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {storytellingInsights.map((card, idx) => {
                const CardIcon = card.icon;
                const cardTheme = card.theme;
                const cleanBadgeText = stripEmojis(card.tag);
                return (
                  <div
                    key={idx}
                    className="bg-surface-raised/60 hover:bg-surface-raised p-4 rounded-xl border border-border shadow-2xs flex flex-col justify-between space-y-2 transition-colors"
                  >
                    <div className="flex items-center justify-between gap-3 pb-3 mb-3 border-b border-border">
                      {/* Bên trái: Duy nhất 1 Icon + Tiêu đề in hoa */}
                      <div className="flex items-center gap-2">
                        <div className={`p-1.5 rounded-lg ${cardTheme.iconBg} ${cardTheme.iconColor}`}>
                          <CardIcon className="w-4 h-4" />
                        </div>
                        <h4 className="text-xs font-bold uppercase tracking-wider text-foreground">
                          {card.phase}
                        </h4>
                      </div>

                      {/* Bên phải: Clean Text Badge - KHÔNG ICON, KHÔNG EMOJI */}
                      <span className="text-[11px] font-medium text-foreground-secondary bg-surface-raised px-2.5 py-0.5 rounded-full border border-border shrink-0 select-none">
                        {cleanBadgeText}
                      </span>
                    </div>

                    <p className="text-xs leading-relaxed font-medium text-foreground-secondary flex-1">
                      {card.text}
                    </p>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 2. Responsive 4-Column Grid: Dynamically Recalculated KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 min-h-[100px]">
            {dynamicKpis.map((kpi: KPIItem, idx: number) => {
              const isPos = kpi.changeType === 'positive';
              const isNeg = kpi.changeType === 'negative';

              let Icon = Hash;
              let accentBorder = 'border-l-foreground-muted';

              const ktype =
                kpi.type ||
                (kpi.icon === 'DollarSign'
                  ? 'currency'
                  : kpi.icon === 'Layers' || kpi.icon === 'Database'
                  ? 'count'
                  : kpi.icon === 'Award' || kpi.icon === 'Tag'
                  ? 'category'
                  : 'number');

              if (ktype === 'count') {
                Icon = Database;
                accentBorder = 'border-l-blue-500';
              } else if (ktype === 'currency') {
                Icon = DollarSign;
                accentBorder = 'border-l-emerald-500';
              } else if (ktype === 'category') {
                Icon = Tag;
                accentBorder = 'border-l-amber-500';
              } else {
                Icon = Hash;
                accentBorder = 'border-l-indigo-500';
              }

              return (
                <div
                  key={idx}
                  className={`group relative bg-surface hover:bg-surface-raised/80 p-4 rounded-xl border border-border hover:border-border-strong border-l-4 ${accentBorder} shadow-xs hover:shadow-md transition-all duration-200 flex flex-col justify-between space-y-2`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-semibold text-foreground-secondary uppercase tracking-wider truncate">
                      {kpi.title}
                    </span>
                    <div className="p-1.5 bg-surface-raised group-hover:bg-surface-overlay text-foreground-muted group-hover:text-accent-primary rounded-lg shrink-0 transition-colors">
                      <Icon className="w-3.5 h-3.5" />
                    </div>
                  </div>

                  <div>
                    {/* font-mono tabular-nums prevents layout shifts during cross-filtering */}
                    <p className="text-2xl font-bold font-mono tabular-nums text-foreground tracking-tight truncate select-all">
                      {kpi.value}
                    </p>
                    <div className="flex items-center justify-between mt-1.5">
                      {kpi.change ? (
                        <span
                          className={`inline-flex items-center text-xs font-mono font-medium px-2 py-0.5 rounded-full ${
                            isPos
                              ? 'bg-accent-verifier/10 text-accent-verifier border border-accent-verifier/20'
                              : isNeg
                              ? 'bg-accent-error/10 text-accent-error border border-accent-error/20'
                              : 'bg-surface-raised text-foreground-secondary'
                          }`}
                        >
                          {isPos && <TrendingUp className="w-3 h-3 mr-1 shrink-0" />}
                          {isNeg && <TrendingDown className="w-3 h-3 mr-1 shrink-0" />}
                          {!isPos && !isNeg && <Minus className="w-3 h-3 mr-1 shrink-0" />}
                          <span className="tabular-nums">{kpi.change}</span>
                        </span>
                      ) : (
                        <span className="text-xs text-foreground-muted">Chỉ số phân tích</span>
                      )}
                      {kpi.subtitle && (
                        <span className="text-xs text-foreground-muted truncate ml-2 font-mono tabular-nums" title={kpi.subtitle}>
                          {kpi.subtitle}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Slicers Filter Bar & Active Filter Bar */}
          {filterCategories.length > 0 && (
            <div className="w-full bg-surface border border-border rounded-2xl p-4 my-3 shadow-xs space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-bold text-foreground uppercase tracking-wider">
                  <Filter className="w-4 h-4 text-accent-primary" />
                  <span>Bộ Lọc Slicers & Tương Tác Dữ Liệu</span>
                </div>
                {hasActiveFilters && (
                  <button
                    type="button"
                    onClick={handleResetFilters}
                    className="text-xs font-semibold text-accent-error hover:opacity-80 flex items-center gap-1 transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-error/40"
                  >
                    <RotateCcw className="w-3.5 h-3.5" /> Đặt lại tất cả
                  </button>
                )}
              </div>

              {/* Slicer Dropdowns without label truncation */}
              <div className="flex flex-wrap items-center gap-3">
                {filterCategories.slice(0, 4).map((catKey) => {
                  const uniqueVals = Array.from(
                    new Set<string>(
                      rawRows
                        .map((r: Record<string, any>) => String(getRowValue(r, catKey) ?? '').trim())
                        .filter(Boolean)
                    )
                  ).sort();

                  const currentVal = activeFilters[catKey] || '';

                  return (
                    <div
                      key={catKey}
                      className={`flex items-center gap-2 bg-surface-raised/50 border ${
                        currentVal && isFilterActive(currentVal)
                          ? 'border-accent-primary ring-1 ring-accent-primary/20'
                          : 'border-border'
                      } rounded-lg px-3 py-1.5 text-xs shadow-2xs transition-all min-w-[160px] max-w-[280px] shrink-0`}
                    >
                      <span
                        className="font-semibold text-foreground-secondary whitespace-nowrap shrink-0 max-w-[140px] truncate"
                        title={catKey.replace(/_/g, ' ')}
                      >
                        {catKey.replace(/_/g, ' ')}:
                      </span>
                      <select
                        value={currentVal}
                        onChange={(e) => handleFilterChange(catKey, e.target.value)}
                        className="bg-transparent font-medium text-foreground focus:outline-none cursor-pointer truncate flex-1 min-w-[70px] text-xs"
                      >
                        <option value="" className="bg-surface text-foreground">
                          -- Tất cả --
                        </option>
                        {uniqueVals.map((v: string) => (
                          <option key={v} value={v} className="bg-surface text-foreground">
                            {v}
                          </option>
                        ))}
                      </select>
                    </div>
                  );
                })}
              </div>

              {/* Active Filters Bar */}
              {Object.keys(activeFilters).some((k) => isFilterActive(activeFilters[k])) && (
                <div className="flex flex-wrap items-center gap-2 pt-2.5 border-t border-border mt-2">
                  <span className="text-xs font-bold text-foreground-secondary uppercase tracking-wider flex items-center gap-1">
                    <Filter className="w-3 h-3 text-accent-primary" /> Đang lọc:
                  </span>
                  {Object.entries(activeFilters)
                    .filter(([_, val]) => isFilterActive(val))
                    .map(([col, val]) => (
                      <span
                        key={col}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-accent-primary/10 text-accent-primary border border-accent-primary/20 shadow-2xs font-mono"
                      >
                        <span className="truncate max-w-[160px]" title={`${col}: ${val}`}>
                          {col.replace(/_/g, ' ')}: <b>{val}</b>
                        </span>
                        <button
                          type="button"
                          onClick={() => handleFilterChange(col, null)}
                          className="w-3.5 h-3.5 flex items-center justify-center rounded-full hover:bg-accent-primary/20 transition-colors text-accent-primary cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-primary/50"
                          title={`Bỏ lọc ${col}`}
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                  <button
                    type="button"
                    onClick={handleResetFilters}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-accent-error/10 text-accent-error hover:bg-accent-error/20 border border-accent-error/20 transition-colors cursor-pointer ml-auto focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-error/40"
                  >
                    <RotateCcw className="w-3.5 h-3.5" /> Xóa tất cả bộ lọc
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* ROW 2: Charts Area */}
      {isSingleChart ? (
        /* SINGLE CHART VIEW MODE: 1 Card Biểu đồ Trọng tâm occupying full width col-span-12 with height h-[480px] */
        <div className="col-span-12 bg-surface p-5 rounded-2xl border border-border shadow-xs hover:shadow-sm transition-shadow min-h-[520px] flex flex-col">
          <div className="flex items-center justify-between border-b border-border pb-3 mb-4">
            <span className="font-bold text-foreground text-sm flex items-center gap-2">
              <BarChart3 className="w-5 h-5 text-accent-primary" />
              {primaryChart?.title || 'Biểu Đồ Xu Hướng Trọng Tâm'}
            </span>
            <span className="text-xs px-2.5 py-1 bg-accent-primary/10 text-accent-primary font-semibold rounded-full border border-accent-primary/20 font-mono">
              Single Chart View
            </span>
          </div>
          {primaryChart ? (
            <EChartComponent
              chartSpec={computedPrimaryChart || primaryChart}
              selectedItem={primarySelected}
              height="480px"
              onChartClick={(params) => handleChartCrossFilter(primaryDimCol, params.name)}
            />
          ) : (
            <div className="h-[480px] flex items-center justify-center text-xs text-foreground-muted italic">
              Không có dữ liệu biểu đồ.
            </div>
          )}
        </div>
      ) : (
        /* FULL DASHBOARD VIEW MODE: (7 : 5 ratio) */
        <div className="grid grid-cols-12 gap-6 min-h-[380px]">
          {/* Left Primary Chart (col-span-7) */}
          <div className="col-span-12 lg:col-span-7 bg-surface p-4 rounded-2xl border border-border shadow-xs hover:shadow-sm transition-shadow min-h-[360px] flex flex-col">
            <div className="flex flex-col border-b border-border pb-2.5 mb-3 gap-1">
              <div className="flex items-center justify-between">
                <span className="font-bold text-foreground text-xs flex items-center gap-1.5">
                  <BarChart3 className="w-4 h-4 text-accent-primary" /> {computedPrimaryChart?.title || primaryChart?.title || 'Biểu Đồ Phân Tích Chính'}
                </span>
                <span className="text-xs text-foreground-muted italic">Click vào cột để lọc chéo (Cross-filter)</span>
              </div>
              {primaryDimCol && (
                <div className="text-[11px] text-foreground-muted flex flex-wrap items-center gap-1.5">
                  <span>Theo <strong className="font-mono text-foreground-secondary">{primaryDimCol}</strong></span>
                  <span className="text-foreground-muted/40">•</span>
                  <span>
                    Xếp hạng: <strong className="font-mono text-foreground-secondary">{primaryMetricCol || 'Giá trị'}</strong>
                  </span>
                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-surface-raised border border-border/80 text-foreground-muted">
                    SUM
                  </span>
                </div>
              )}
            </div>
            {primaryChart ? (
              <EChartComponent
                chartSpec={computedPrimaryChart || primaryChart}
                selectedItem={primarySelected}
                height="320px"
                onChartClick={(params) => handleChartCrossFilter(primaryDimCol, params.name)}
              />
            ) : (
              <div className="h-[320px] flex items-center justify-center text-xs text-foreground-muted italic">
                Không có dữ liệu biểu đồ.
              </div>
            )}
          </div>

          {/* Right Donut Chart (col-span-5) */}
          <div className="col-span-12 lg:col-span-5 bg-surface p-4 rounded-2xl border border-border shadow-xs hover:shadow-sm transition-shadow min-h-[360px] flex flex-col">
            <div className="flex flex-col border-b border-border pb-2.5 mb-3 gap-1">
              <div className="flex items-center justify-between">
                <span className="font-bold text-foreground text-xs flex items-center gap-1.5">
                  <PieChart className="w-4 h-4 text-teal-500" /> {computedSecondaryChart?.title || secondaryChart?.title || 'Tỷ Trọng & Thị Phần'}
                </span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-teal-500/10 text-teal-500 border border-teal-500/20 font-semibold">
                  Donut View
                </span>
              </div>
              {/* Phụ đề động (Subtitle): Minh bạch nguồn gốc cột & hàm đo lường */}
              <div className="text-[11px] text-foreground-muted flex flex-wrap items-center gap-1.5">
                <span>Theo <strong className="font-mono text-foreground-secondary">{secondaryDimCol || 'Phân loại'}</strong></span>
                <span className="text-foreground-muted/40">•</span>
                <span>
                  Đo lường: <strong className="font-mono text-foreground-secondary">
                    {computedSecondaryChart?.measure && computedSecondaryChart.measure !== 'count' && computedSecondaryChart.measure !== 'value'
                      ? `Tổng ${computedSecondaryChart.measure}`
                      : 'Số lượng đơn hàng (Số dòng)'}
                  </strong>
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-surface-raised border border-border/80 text-foreground-muted">
                  {computedSecondaryChart?.aggregation || (computedSecondaryChart?.measure && computedSecondaryChart.measure !== 'count' ? 'SUM' : 'COUNT')}
                </span>
              </div>
            </div>
            {secondaryChart ? (
              <EChartComponent
                chartSpec={computedSecondaryChart || secondaryChart}
                isPie={true}
                selectedItem={secondarySelected}
                height="320px"
                onChartClick={(params) => handleChartCrossFilter(secondaryDimCol, params.name)}
              />
            ) : (
              <div className="h-[320px] flex items-center justify-center text-xs text-foreground-muted italic">
                Không có dữ liệu biểu đồ.
              </div>
            )}
          </div>
        </div>
      )}

      {/* ROW 3: AG Grid Data Table (col-span-12) */}
      <div className="bg-surface p-5 rounded-xl border border-border shadow-xs space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border pb-3">
          <div className="flex items-center space-x-2">
            <TableIcon className="w-4 h-4 text-accent-primary" />
            <span className="font-bold text-foreground text-sm">
              {spec.table?.title || 'Bảng Chi Tiết Dữ Liệu'}
            </span>
            <span className="px-2.5 py-1 bg-accent-primary/10 text-accent-primary border border-accent-primary/20 rounded-md text-xs font-semibold font-mono tabular-nums">
              ( Hiển thị {filteredRows.length.toLocaleString()} / {(spec?.totalRows || rawRows.length).toLocaleString()} bản ghi )
            </span>
          </div>

          <div className="flex items-center space-x-2">
            {/* Quick Search Input */}
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-foreground-muted absolute left-2.5 top-2.5" />
              <input
                type="text"
                placeholder="Tìm kiếm nhanh..."
                value={quickFilterText}
                onChange={(e) => setQuickFilterText(e.target.value)}
                className="pl-8 pr-3 py-1.5 bg-surface-raised border border-border rounded-lg text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-accent-primary w-44 sm:w-56"
              />
            </div>

            <button
              type="button"
              onClick={onExportCSV}
              className="flex items-center gap-1.5 px-3 py-1.5 border border-border hover:bg-surface-raised text-foreground rounded-lg text-xs font-semibold transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
            >
              <Download className="w-3.5 h-3.5 text-accent-primary" /> CSV
            </button>

            <button
              type="button"
              onClick={onPrintReport}
              className="flex items-center gap-1.5 px-3 py-1.5 border border-border hover:bg-surface-raised text-foreground rounded-lg text-xs font-semibold transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
            >
              <Printer className="w-3.5 h-3.5 text-foreground-muted" /> In Báo Cáo
            </button>
          </div>
        </div>

        <div
          className={`ag-theme-alpine ${
            isDark ? 'ag-theme-quartz-dark ag-theme-alpine-dark' : 'ag-theme-quartz'
          } w-full h-[580px] rounded-xl border border-border overflow-hidden`}
        >
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
