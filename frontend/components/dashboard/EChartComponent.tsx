'use client';

import React, { useRef, useEffect, useMemo, useCallback } from 'react';
import ReactECharts from 'echarts-for-react';
import { ChartItem } from '../../lib/types';
import { useIsDark } from '../../lib/useIsDark';
import { formatAxisValue, formatChartMetric } from '../../lib/formatters';

export interface ChartClickParams {
  name: string;
  value: any;
  seriesName: string;
  dataIndex: number;
}

interface EChartComponentProps {
  chartSpec?: ChartItem;
  option?: Record<string, any>;
  onChartClick?: (params: ChartClickParams) => void;
  isPie?: boolean;
  height?: string;
  selectedItem?: string | null;
}

// Color palettes
const DARK_PALETTE = ['#6366f1', '#f59e0b', '#10b981', '#3b82f6', '#8b5cf6', '#ec4899', '#06b6d4'];
const LIGHT_PALETTE = ['#4F46E5', '#F37021', '#10B981', '#06B6D4', '#8B5CF6', '#EC4899', '#F59E0B'];

const parseNum = (val: any): number => {
  if (typeof val === 'number') return isNaN(val) ? 0 : val;
  if (!val) return 0;
  const cleaned = String(val).replace(/[^0-9.-]+/g, '');
  const num = parseFloat(cleaned);
  return isNaN(num) ? 0 : num;
};

export const EChartComponent: React.FC<EChartComponentProps> = ({
  chartSpec,
  option,
  onChartClick,
  isPie = false,
  height = '320px',
  selectedItem = null,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReactECharts>(null);
  const isDark = useIsDark();

  // ResizeObserver for responsive charts when container or sidebar changes
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver(() => {
      const instance = chartRef.current?.getEchartsInstance?.();
      if (instance && typeof instance.resize === 'function') {
        instance.resize();
      }
    });
    observer.observe(containerRef.current);

    // Initial resize after a tick to make sure container dimensions are stable
    const timer = setTimeout(() => {
      const instance = chartRef.current?.getEchartsInstance?.();
      if (instance && typeof instance.resize === 'function') {
        instance.resize();
      }
    }, 60);

    return () => {
      clearTimeout(timer);
      observer.disconnect();
    };
  }, []);

  // 1. Lưu callback vào ref để tránh stale closure mà không làm re-bind listener
  const onChartClickRef = useRef(onChartClick);
  useEffect(() => {
    onChartClickRef.current = onChartClick;
  }, [onChartClick]);

  // 2. Gắn listener duy nhất vào instance
  const bindEvents = useCallback((chart: any) => {
    if (!chart || typeof chart.on !== 'function') return;

    const handleClick = (params: any) => {
      // Chỉ kích hoạt khi click vào một thành phần thuộc series (cột hoặc lát cắt bánh)
      if (params && (params.componentType === 'series' || params.seriesType)) {
        const categoryName =
          params.name ||
          (typeof params.data === 'object' && params.data ? params.data.name : null) ||
          (typeof params.value === 'string' ? params.value : null);

        if (categoryName && onChartClickRef.current) {
          onChartClickRef.current({
            name: String(categoryName).trim(),
            value: params.value,
            seriesName: params.seriesName || '',
            dataIndex: typeof params.dataIndex === 'number' ? params.dataIndex : -1,
          });
        }
      }
    };

    chart.off('click');
    chart.on('click', handleClick);
  }, []);

  // Đảm bảo event listener luôn được gắn khi instance sẵn sàng
  useEffect(() => {
    const chart = chartRef.current?.getEchartsInstance?.();
    if (chart) {
      bindEvents(chart);
    }
  }, [bindEvents]);

  const palette = isDark ? DARK_PALETTE : LIGHT_PALETTE;
  const textColor = isDark ? '#a1a1aa' : '#475569';
  const titleColor = isDark ? '#fafafa' : '#1E293B';
  const gridLineColor = isDark ? '#27272a' : '#F1F5F9';
  const axisLineColor = isDark ? '#3f3f46' : '#CBD5E1';
  const tooltipBg = isDark ? '#18181b' : '#ffffff';
  const tooltipBorder = isDark ? '#27272a' : '#e4e4e7';

  // Custom Glassmorphism tooltip styling
  const tooltipStyle = useMemo(
    () => ({
      backgroundColor: isDark ? 'rgba(24, 24, 27, 0.92)' : 'rgba(255, 255, 255, 0.95)',
      borderColor: isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.08)',
      borderWidth: 1,
      borderRadius: 12,
      padding: [10, 14],
      textStyle: {
        color: isDark ? '#f4f4f5' : '#1e293b',
        fontSize: 12,
        fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
      },
      extraCssText: `
        box-shadow: 0 8px 32px rgba(0,0,0,${isDark ? '0.5' : '0.12'});
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
      `.trim(),
    }),
    [isDark]
  );

  const hasSelection = Boolean(selectedItem && selectedItem.trim());
  const selectedNorm = selectedItem ? selectedItem.trim().toLowerCase() : '';

  // Generate Cartesian or Pie option
  const computedOption = useMemo(() => {
    if (option) return option;
    if (!chartSpec) return null;

    const rawData = chartSpec.data || [];

    // 1. PIE / DONUT CHART
    if (isPie || chartSpec.type === 'pie' || (chartSpec.type as string) === 'donut') {
      const samplePieItem = rawData[0] || {};
      const nameKey =
        chartSpec.name_key ||
        Object.keys(samplePieItem).find((k) => typeof samplePieItem[k] === 'string' && k !== 'type') ||
        'name';

      const valKey =
        chartSpec.value_key ||
        Object.keys(samplePieItem).find((k) => typeof samplePieItem[k] === 'number') ||
        'value';

      const pieBorderColor = isDark ? '#18181b' : '#ffffff';

      let pieData = rawData.map((d: Record<string, unknown>) => {
        const rawVal = d[valKey] ?? d.value ?? d.y ?? d.count ?? 0;
        const val = typeof rawVal === 'number' ? rawVal : parseNum(rawVal);
        const sliceName = String(d[nameKey] ?? d.name ?? d.label ?? d.x ?? d.category ?? 'Khác').trim();
        const isSelected = hasSelection && sliceName.toLowerCase() === selectedNorm;
        const opacity = hasSelection ? (isSelected ? 1 : 0.35) : 1;

        return {
          name: sliceName || 'Khác',
          value: isNaN(val) ? 0 : val,
          itemStyle: {
            opacity,
            borderRadius: 6,
            borderColor: isSelected ? (isDark ? '#fafafa' : '#1E293B') : pieBorderColor,
            borderWidth: isSelected ? 3 : 2,
            shadowBlur: isSelected ? 10 : 0,
            shadowColor: isSelected ? 'rgba(0, 0, 0, 0.4)' : 'transparent',
          },
        };
      });

      // Lọc bỏ các mục có giá trị 0 nếu mảng có các mục > 0
      const positiveItems = pieData.filter((item) => item.value > 0);
      if (positiveItems.length > 0) {
        pieData = positiveItems;
      }

      const dimensionColumnName =
        chartSpec.dimension ||
        (chartSpec.name_key && chartSpec.name_key !== 'name' && chartSpec.name_key !== 'x' ? chartSpec.name_key : '') ||
        (chartSpec.x_axis_key && chartSpec.x_axis_key !== 'x' ? chartSpec.x_axis_key : '') ||
        nameKey ||
        'Phân loại';

      const measureColumnName =
        chartSpec.measure && chartSpec.measure !== 'count' && chartSpec.measure !== 'value'
          ? chartSpec.measure
          : (chartSpec.value_key && !['value', 'val', 'y', 'count'].includes(chartSpec.value_key)
              ? chartSpec.value_key
              : (chartSpec.y_axis_key && chartSpec.y_axis_key !== 'y'
                  ? chartSpec.y_axis_key
                  : ''));

      return {
        backgroundColor: 'transparent',
        color: palette,
        animationDuration: 400,
        animationEasing: 'cubicOut',
        tooltip: {
          ...tooltipStyle,
          trigger: 'item' as const,
          formatter: (params: any) => {
            const rawVal = typeof params.value === 'number' ? params.value : parseNum(params.value);
            const { formatted, compact } = formatChartMetric(rawVal, measureColumnName);
            const pct = params.percent !== undefined ? Number(params.percent).toFixed(2) : '0.00';
            const displayDim = dimensionColumnName && dimensionColumnName !== 'name' ? dimensionColumnName : 'Phân loại';
            const displayMeasure = measureColumnName ? measureColumnName : 'Số dòng (Count)';

            return `
              <div style="font-family: inherit; font-size: 12px; line-height: 1.45; min-width: 180px;">
                <div style="display: flex; align-items: center; gap: 8px; padding-bottom: 6px; border-bottom: 1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)'}; font-weight: 600; color: ${isDark ? '#f4f4f5' : '#1e293b'};">
                  <span style="display:inline-block;width:9px;height:9px;border-radius:50%;background-color:${params.color};flex-shrink:0;"></span>
                  <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${params.name}</span>
                </div>
                <div style="padding-top: 6px; color: ${isDark ? '#a1a1aa' : '#64748b'}; font-size: 11px;">
                  Cột dữ liệu: <span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-weight: 600; color: ${isDark ? '#e4e4e7' : '#334155'};">${displayDim}</span>
                </div>
                <div style="color: ${isDark ? '#a1a1aa' : '#64748b'}; font-size: 11px;">
                  Chỉ số đo lường: <span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-weight: 600; color: ${isDark ? '#e4e4e7' : '#334155'};">${displayMeasure}</span>
                </div>
                <div style="color: ${isDark ? '#a1a1aa' : '#64748b'}; font-size: 11px;">
                  Giá trị: <span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-weight: 700; color: #10b981;">${formatted}</span>
                  ${compact !== formatted ? `<span style="color: ${isDark ? '#71717a' : '#94a3b8'}; margin-left: 4px;">(${compact})</span>` : ''}
                </div>
                <div style="color: ${isDark ? '#a1a1aa' : '#64748b'}; font-size: 11px;">
                  Tỷ trọng: <span style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-weight: 700; color: #f59e0b;">${pct}%</span>
                </div>
              </div>
            `;
          },
        },
        legend: {
          orient: 'vertical' as const,
          left: 'left',
          bottom: 'bottom',
          type: 'scroll',
          textStyle: { fontSize: 10, color: textColor },
        },
        series: [
          {
            type: 'pie',
            radius: ['40%', '70%'],
            avoidLabelOverlap: true,
            minAngle: 5,
            itemStyle: { borderRadius: 6, borderColor: pieBorderColor, borderWidth: 2 },
            label: {
              show: true,
              formatter: '{b}: {d}%',
              fontSize: 11,
              color: textColor,
            },
            emphasis: {
              label: { show: true, fontSize: 12, fontWeight: 'bold' as const },
              itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.3)' },
            },
            data: pieData,
          },
        ],
      };
    }

    // 2. CARTESIAN CHART (BAR / LINE)
    const isLine = chartSpec.type === 'line';
    const sampleItem = rawData[0] || {};
    const inferredXKey =
      chartSpec.x_axis_key ||
      chartSpec.xAxisKey ||
      Object.keys(sampleItem).find((k) => typeof sampleItem[k] === 'string' && k !== 'type') ||
      Object.keys(sampleItem)[0] ||
      'x';

    const inferredYKey =
      chartSpec.y_axis_key ||
      chartSpec.yAxisKey ||
      Object.keys(sampleItem).find((k) => typeof sampleItem[k] === 'number') ||
      Object.keys(sampleItem)[1] ||
      'y';

    let xCategories: string[] = chartSpec.x_data || [];
    if (!xCategories || xCategories.length === 0) {
      xCategories = rawData.map((item: Record<string, unknown>, idx: number) => {
        const val = item[inferredXKey] ?? item.name ?? item.x ?? item.category ?? item.label ?? item.month;
        if (val !== undefined && val !== null && String(val).trim() !== '') {
          return String(val).trim();
        }
        const firstStrVal = Object.values(item).find((v) => typeof v === 'string');
        return firstStrVal ? String(firstStrVal).trim() : `Item ${idx + 1}`;
      });
    }

    const seriesKeys = chartSpec.series_keys || [inferredYKey];
    const builtSeries = seriesKeys.map((sKey: string, sIdx: number) => {
      const seriesColor = palette[sIdx % palette.length];
      const dataPoints = rawData.map((d: Record<string, unknown>) => {
        const rawVal = d[sKey] ?? d.value ?? d.y ?? d.count ?? 0;
        const val = typeof rawVal === 'number' ? rawVal : parseNum(rawVal);
        return isNaN(val) ? 0 : val;
      });

      if (isLine) {
        return {
          name: sKey,
          type: 'line',
          smooth: true,
          showSymbol: dataPoints.length <= 25,
          symbolSize: 6,
          data: dataPoints,
          itemStyle: { color: seriesColor },
          lineStyle: { width: 2.5, color: seriesColor },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: seriesColor + (isDark ? '40' : '30') },
                { offset: 1, color: seriesColor + '00' },
              ],
            },
          },
        };
      }

      // Bar Chart with Visual Highlight / Dimming
      const styledBarData = dataPoints.map((val: number, idx: number) => {
        const catName = String(xCategories[idx] || '').trim();
        const isSelected = hasSelection && catName.toLowerCase() === selectedNorm;
        const opacity = hasSelection ? (isSelected ? 1 : 0.35) : 1;

        return {
          value: val,
          name: catName,
          itemStyle: {
            opacity,
            borderRadius: [4, 4, 0, 0],
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: seriesColor },
                { offset: 1, color: seriesColor + 'CC' },
              ],
            },
            borderColor: isSelected ? (isDark ? '#fafafa' : '#1E293B') : 'transparent',
            borderWidth: isSelected ? 2 : 0,
            shadowBlur: isSelected ? 8 : 0,
            shadowColor: isSelected ? (isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.3)') : 'transparent',
          },
        };
      });

      return {
        name: sKey,
        type: 'bar',
        barMaxWidth: 36,
        data: styledBarData,
      };
    });

    return {
      backgroundColor: 'transparent',
      color: palette,
      animationDuration: 400,
      animationEasing: 'cubicOut',
      tooltip: {
        ...tooltipStyle,
        trigger: 'axis' as const,
        axisPointer: { type: isLine ? ('cross' as const) : ('shadow' as const) },
        valueFormatter: (val: any) => {
          const num = typeof val === 'number' ? val : Number(val);
          return isNaN(num) ? String(val) : formatAxisValue(num, chartSpec.isMonetary, chartSpec.unit);
        },
      },
      legend: {
        show: builtSeries.length > 1,
        top: 0,
        right: '4%',
        textStyle: { fontSize: 11, color: textColor },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: 50, // Đảm bảo đủ khoảng trống cho dataZoom ở đáy (bottom: 6, height: 18)
        containLabel: true,
      },
      dataZoom:
        xCategories.length > 10
          ? [
              {
                type: 'slider',
                show: true,
                xAxisIndex: [0],
                startValue: 0,
                endValue: Math.min(14, xCategories.length - 1),
                height: 18,
                bottom: 6,
                handleSize: '80%',
                brushSelect: false, // Không cho slider chiếm quyền click của các cột
                borderColor: isDark ? '#27272a' : '#e2e8f0',
                fillerColor: isDark ? 'rgba(99, 102, 241, 0.2)' : 'rgba(79, 70, 229, 0.15)',
                textStyle: { color: textColor, fontSize: 10 },
              },
              {
                type: 'inside',
                xAxisIndex: [0],
                zoomOnMouseWheel: false,
                moveOnMouseMove: true,
              },
            ]
          : undefined,
      xAxis: {
        type: 'category' as const,
        data: xCategories,
        axisLabel: {
          interval: 0,
          rotate: xCategories.length > 5 ? 30 : 0,
          fontSize: 10,
          color: textColor,
          overflow: 'truncate',
          width: 80,
          formatter: (val: string) => {
            const s = String(val ?? '');
            return s.length > 12 ? s.slice(0, 11) + '…' : s;
          },
        },
        axisLine: { lineStyle: { color: axisLineColor } },
      },
      yAxis: {
        type: 'value' as const,
        axisLabel: {
          fontSize: 10,
          color: textColor,
          formatter: (val: number) => formatAxisValue(val, chartSpec.isMonetary, chartSpec.unit),
        },
        splitLine: { lineStyle: { type: 'dashed' as const, color: gridLineColor } },
      },
      series: builtSeries,
    };
  }, [option, chartSpec, isPie, isDark, palette, textColor, axisLineColor, gridLineColor, tooltipStyle, hasSelection, selectedNorm]);

  if (!computedOption) {
    return (
      <div
        style={{ minHeight: height }}
        className="w-full min-h-[300px] flex items-center justify-center text-xs text-slate-400 dark:text-zinc-500 italic"
      >
        Chưa có dữ liệu biểu đồ.
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      style={{ minHeight: height }}
      className="w-full max-w-full overflow-hidden min-w-0 min-h-[300px]"
    >
      <ReactECharts
        ref={chartRef}
        theme={isDark ? 'dark' : undefined}
        option={computedOption}
        style={{ height, width: '100%' }}
        notMerge={true}
        lazyUpdate={true}
        onChartReady={bindEvents}
      />
    </div>
  );
};
