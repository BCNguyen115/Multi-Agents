/** The one chart of the console's front page: LLM cost per day, drawn from the numbers the server computed. */

import type { ChartTheme } from './chartOption';
import type { CostDay } from './adminApi';

export function dailyCostOption(days: CostDay[], theme: ChartTheme, formatCost: (amount: number) => string) {
  const text = { color: theme.muted, fontFamily: theme.font };
  return {
    aria: { enabled: true },
    grid: { left: 4, right: 8, top: 16, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: unknown) => formatCost(Number(value)),
      backgroundColor: theme.surface,
      borderColor: theme.grid,
      textStyle: { color: theme.fg, fontFamily: theme.font },
    },
    xAxis: { type: 'category', data: days.map((d) => d.day.slice(5)), axisTick: { show: false }, axisLine: { lineStyle: { color: theme.axis } }, axisLabel: text },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: theme.grid } }, axisLabel: { ...text, formatter: (value: number) => formatCost(value) } },
    series: [{ type: 'bar', data: days.map((d) => d.cost), barMaxWidth: 36, itemStyle: { color: theme.palette[3] ?? theme.palette[0], borderRadius: [4, 4, 0, 0] } }],
  };
}

/** Thumbs per day, stacked: helpful in the accent colour, not helpful in the error colour. The numbers are the server's. */
export function feedbackOption(days: { day: string; up: number; down: number }[], theme: ChartTheme, names: { up: string; down: string }) {
  const text = { color: theme.muted, fontFamily: theme.font };
  return {
    aria: { enabled: true },
    legend: { data: [names.up, names.down], top: 0, textStyle: text },
    grid: { left: 4, right: 8, top: 32, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: theme.surface,
      borderColor: theme.grid,
      textStyle: { color: theme.fg, fontFamily: theme.font },
    },
    xAxis: { type: 'category', data: days.map((d) => d.day.slice(5)), axisTick: { show: false }, axisLine: { lineStyle: { color: theme.axis } }, axisLabel: text },
    yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: theme.grid } }, axisLabel: text },
    series: [
      { name: names.up, type: 'bar', stack: 'feedback', data: days.map((d) => d.up), barMaxWidth: 36, itemStyle: { color: theme.palette[3] ?? theme.palette[0] } },
      { name: names.down, type: 'bar', stack: 'feedback', data: days.map((d) => d.down), barMaxWidth: 36, itemStyle: { color: theme.negative, borderRadius: [4, 4, 0, 0] } },
    ],
  };
}
