'use client';

import React from 'react';
import ReactECharts from 'echarts-for-react';
import { ChartItem } from '../../lib/types';

interface EChartComponentProps {
  chartSpec: ChartItem;
  onChartClick?: (params: any) => void;
  isPie?: boolean;
  height?: string;
}

export const EChartComponent: React.FC<EChartComponentProps> = ({
  chartSpec,
  onChartClick,
  isPie = false,
  height = '320px',
}) => {
  if (!chartSpec) return null;

  const rawData = chartSpec.data || [];

  // Cartesian Chart Renderer (Line & Bar) with Multi-Series & markLine Support
  if ((chartSpec.type === 'line' || chartSpec.type === 'bar' || chartSpec.type === 'scatter') && !isPie) {
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

    // 1. Map danh mục Trục X
    let xCategories: string[] = chartSpec.x_data || [];
    if (!xCategories || xCategories.length === 0) {
      xCategories = rawData.map((item: any, idx: number) => {
        const val = item[inferredXKey] ?? item.x ?? item.name ?? item.category ?? item.label ?? item.month;
        if (val !== undefined && val !== null && String(val).trim() !== '') {
          return String(val);
        }
        const firstStrVal = Object.values(item).find((v) => typeof v === 'string');
        return firstStrVal ? String(firstStrVal) : `Mục ${idx + 1}`;
      });
    }

    const hasAvgLine = chartSpec.extra_features?.includes('average_line') || chartSpec.showAverageLine || (chartSpec as any).average_val !== undefined;
    const defaultNativeMarkLine = {
      silent: true,
      symbol: ['none', 'none'],
      label: {
        show: true,
        formatter: (params: any) => {
          const val = Number(params.value);
          const formatted = chartSpec.isMonetary
            ? `$${val.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 2 })}`
            : val.toLocaleString(undefined, { maximumFractionDigits: 2 });
          return `Mức Trung Bình: ${formatted}`;
        },
        position: 'end',
        fontSize: 11,
        fontWeight: 'bold',
        color: '#EF4444',
      },
      lineStyle: {
        type: 'dashed',
        color: '#EF4444',
        width: 2,
      },
      data: [{ type: 'average', name: 'Trung Bình' }],
    };

    // 2. Build ECharts Series array
    let builtSeries: any[] = [];

    if (chartSpec.series && Array.isArray(chartSpec.series) && chartSpec.series.length > 0) {
      builtSeries = chartSpec.series.map((s: any, idx: number) => {
        const sType = s.type || (isLine ? 'line' : 'bar');
        const sData = Array.isArray(s.data)
          ? s.data
          : rawData.map((item: any) => {
              const val = item[s.key || inferredYKey] ?? item.y ?? item.value;
              const num = Number(val);
              return isNaN(num) ? 0 : num;
            });

        return {
          name: s.name || (idx === 0 ? 'Giá trị chính' : `Chuỗi ${idx + 1}`),
          type: sType,
          smooth: s.smooth ?? (sType === 'line'),
          symbolSize: s.symbolSize || 8,
          barMaxWidth: 40,
          lineStyle: s.lineStyle || { width: sType === 'line' ? 3 : 2, color: s.color || '#4F46E5' },
          itemStyle: s.itemStyle || {
            color: s.color || (idx === 0 ? '#4F46E5' : idx === 1 ? '#EF4444' : '#10B981'),
            borderRadius: sType === 'bar' ? [6, 6, 0, 0] : undefined,
          },
          markLine: s.markLine || (idx === 0 && hasAvgLine ? defaultNativeMarkLine : undefined),
          data: sData,
        };
      });
    } else {
      const yValues = rawData.map((item: any) => {
        const val = item[inferredYKey] ?? item.y ?? item.value ?? item.count;
        const num = Number(val);
        return isNaN(num) ? 0 : num;
      });

      builtSeries = [
        {
          name: chartSpec.metric_label || 'Giá Trị',
          type: isLine ? 'line' : 'bar',
          smooth: true,
          symbolSize: 8,
          barMaxWidth: 40,
          itemStyle: {
            color: '#4F46E5',
            borderRadius: isLine ? undefined : [6, 6, 0, 0],
          },
          lineStyle: { width: 3, color: '#4F46E5' },
          markLine: hasAvgLine ? defaultNativeMarkLine : undefined,
          data: yValues,
        },
      ];
    }

    const cartesianOption = {
      title: {
        text: chartSpec.title || 'Phân Tích Thống Kê',
        left: 'left',
        textStyle: { fontSize: 13, fontWeight: 'bold', color: '#1E293B' },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: isLine ? 'cross' : 'shadow' },
        formatter: (params: any) => {
          if (Array.isArray(params) && params.length > 0) {
            let res = `<div style="font-weight:bold;margin-bottom:4px;">${params[0].axisValueLabel}</div>`;
            params.forEach((item: any) => {
              const valFormatted = typeof item.value === 'number'
                ? (chartSpec.isMonetary ? `$${item.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : item.value.toLocaleString())
                : item.value;
              res += `<div><span style="display:inline-block;margin-right:4px;border-radius:10px;width:10px;height:10px;background-color:${item.color};"></span>${item.seriesName}: <b>${valFormatted}</b></div>`;
            });
            return res;
          }
          return '';
        },
      },
      legend: {
        show: builtSeries.length > 1,
        top: 0,
        right: '4%',
        textStyle: { fontSize: 11, color: '#475569' },
      },
      grid: { left: '3%', right: '5%', bottom: '10%', containLabel: true },
      xAxis: {
        type: 'category',
        data: xCategories,
        axisLabel: { interval: 0, rotate: xCategories.length > 6 ? 30 : 0, fontSize: 10, color: '#475569' },
        axisLine: { lineStyle: { color: '#CBD5E1' } },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          fontSize: 10,
          color: '#475569',
          formatter: (val: number) => (chartSpec.isMonetary ? `$${val.toLocaleString()}` : val.toLocaleString()),
        },
        splitLine: { lineStyle: { type: 'dashed', color: '#F1F5F9' } },
      },
      series: builtSeries,
    };

    return (
      <div className="w-full max-w-full overflow-hidden">
        <ReactECharts
          option={cartesianOption}
          style={{ height, width: '100%' }}
          onEvents={onChartClick ? { click: onChartClick } : undefined}
          notMerge={true}
          lazyUpdate={true}
        />
      </div>
    );
  }

  // Pie / Donut Chart Renderer
  const pieData = rawData.map((item: any, idx: number) => {
    const nameVal = item.name ?? item.x ?? item.category ?? item.label;
    const nameStr = (nameVal !== undefined && nameVal !== null && String(nameVal).trim() !== '')
      ? String(nameVal)
      : `Nhóm ${idx + 1}`;
    const rawVal = item.value ?? item.y ?? item.count ?? 0;
    const numVal = typeof rawVal === 'number' ? rawVal : Number(rawVal) || 0;
    return { name: nameStr, value: numVal };
  });

  const pieOption = {
    title: {
      text: chartSpec.title || 'Tỷ Trọng Cơ Cấu',
      left: 'center',
      textStyle: { fontSize: 14, fontWeight: 'bold', color: '#1E293B' },
    },
    tooltip: {
      trigger: 'item',
      formatter: (params: any) => {
        const valFormatted = (typeof params.value === 'number' && chartSpec.isMonetary)
          ? `$${params.value.toLocaleString()}`
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

  return (
    <div className="w-full max-w-full overflow-hidden">
      <ReactECharts
        option={pieOption}
        style={{ height: '320px', width: '100%' }}
        onEvents={onChartClick ? { click: onChartClick } : undefined}
        notMerge={true}
        lazyUpdate={true}
      />
    </div>
  );
};
