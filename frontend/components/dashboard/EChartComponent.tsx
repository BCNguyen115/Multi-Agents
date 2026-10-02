'use client';

import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import ReactECharts from 'echarts-for-react';
import type { ECharts } from 'echarts';
import type { ChartItem } from '../../lib/types';
import { useIsDark } from '../../lib/useIsDark';
import { buildOption, ChartTheme, isFilterableChart } from '../../lib/chartOption';

interface EChartComponentProps {
  chart: ChartItem;
  /** Category currently used as a cross-filter (all others are dimmed). */
  selected?: string | null;
  height?: string;
  /** Called with the clicked category name (only wired for filterable charts). */
  onSelect?: (name: string) => void;
}

const DARK_PALETTE = ['#6366f1', '#f59e0b', '#10b981', '#3b82f6', '#8b5cf6', '#ec4899', '#06b6d4'];
const LIGHT_PALETTE = ['#4F46E5', '#F37021', '#10B981', '#06B6D4', '#8B5CF6', '#EC4899', '#F59E0B'];

/** Theme colours come from the global CSS design tokens (re-read whenever the theme flips). */
function readTheme(isDark: boolean): ChartTheme {
  const token = (name: string, fallback: string) =>
    (typeof document === 'undefined' ? '' : getComputedStyle(document.documentElement).getPropertyValue(name).trim()) || fallback;
  return {
    palette: isDark ? DARK_PALETTE : LIGHT_PALETTE,
    text: token('--foreground-secondary', '#64748b'),
    muted: token('--foreground-muted', '#94a3b8'),
    grid: token('--border', '#e2e8f0'),
    axis: token('--border-strong', '#cbd5e1'),
    surface: token('--surface', isDark ? '#0f172a' : '#ffffff'),
    fg: token('--foreground', isDark ? '#f8fafc' : '#0f172a'),
    positive: token('--accent-verifier', '#10b981'),
    negative: token('--accent-error', '#ef4444'),
  };
}

export const EChartComponent: React.FC<EChartComponentProps> = ({ chart, selected = null, height = '320px', onSelect }) => {
  const isDark = useIsDark();
  const chartRef = useRef<ReactECharts>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const filterable = isFilterableChart(chart);
  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  // eslint-disable-next-line react-hooks/exhaustive-deps -- isDark is the re-read trigger for the CSS variables
  const theme = useMemo(() => readTheme(isDark), [isDark]);
  const option = useMemo(() => buildOption(chart, theme, selected), [chart, theme, selected]);

  // Resize with the container (sidebar toggles, fullscreen, grid changes)
  useEffect(() => {
    if (!containerRef.current) return undefined;
    const observer = new ResizeObserver(() => chartRef.current?.getEchartsInstance()?.resize());
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const bindClick = useCallback(
    (instance: ECharts) => {
      instance.off('click');
      if (!filterable) return;
      instance.on('click', (params: unknown) => {
        const { componentType, name } = params as { componentType?: string; name?: string };
        if (componentType === 'series' && name) onSelectRef.current?.(String(name));
      });
    },
    [filterable]
  );

  useEffect(() => {
    const instance = chartRef.current?.getEchartsInstance();
    if (instance) bindClick(instance);
  }, [bindClick]);

  return (
    <div ref={containerRef} style={{ height }} className="w-full min-w-0 overflow-hidden" data-testid={`chart-${chart.id}`}>
      <ReactECharts
        ref={chartRef}
        theme={isDark ? 'dark' : undefined}
        option={{ backgroundColor: 'transparent', animationDuration: 350, ...option }}
        style={{ height: '100%', width: '100%', cursor: filterable ? 'pointer' : 'default' }}
        notMerge
        onChartReady={bindClick}
      />
    </div>
  );
};
