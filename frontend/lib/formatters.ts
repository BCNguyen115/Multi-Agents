/**
 * Universal number formatter. Decides purely from the value's magnitude plus the
 * unit / monetary flag inferred by the backend — never from a column name.
 */

export interface MetricFormatOptions {
  isMonetary?: boolean;
  unit?: string;
}

// Placeholder units the backend emits when a measure has no real unit — never shown as a suffix.
const NEUTRAL_UNITS = new Set(['bản ghi', 'hàng', 'number', 'đơn vị', 'unit', 'đơn vị tiền tệ']);

const isMoney = (o?: MetricFormatOptions) => Boolean(o?.isMonetary) || o?.unit === '$' || o?.unit === 'USD';

export function formatUniversalMetric(val: number | null | undefined, options?: MetricFormatOptions): string {
  if (val === null || val === undefined || Number.isNaN(val)) return '0';

  if (options?.unit === '%') {
    // 0..1 scale is treated as a fraction
    return `${(Math.abs(val) <= 1 && val !== 0 ? val * 100 : val).toFixed(1)}%`;
  }

  const abs = Math.abs(val);
  let formatted: string;
  if (abs >= 1e12) formatted = `${(val / 1e12).toFixed(2)}T`;
  else if (abs >= 1e9) formatted = `${(val / 1e9).toFixed(2)}B`;
  else if (abs >= 1e6) formatted = `${(val / 1e6).toFixed(2)}M`;
  else if (abs >= 1e3) formatted = `${(val / 1e3).toFixed(1)}K`;
  else formatted = Number.isInteger(val) ? val.toLocaleString('en-US') : val.toFixed(2);

  const money = isMoney(options);
  const unit = options?.unit;
  const showUnit = !money && unit && !NEUTRAL_UNITS.has(unit.toLowerCase()) && !unit.startsWith('Top:');
  return `${money ? '$' : ''}${formatted}${showUnit ? ` ${unit}` : ''}`;
}

/** Full-precision (grouped) + compact rendering of the same value, for tooltips. */
export function formatChartMetric(
  value: number | null | undefined,
  options?: MetricFormatOptions
): { formatted: string; compact: string } {
  if (value === null || value === undefined || Number.isNaN(value)) return { formatted: '0', compact: '0' };
  const money = isMoney(options) ? '$' : '';
  const pct = options?.unit === '%' ? '%' : '';
  const full = value.toLocaleString('en-US', { maximumFractionDigits: 2 });
  return {
    formatted: `${money}${full}${pct}`,
    compact: pct ? formatUniversalMetric(value, options) : formatUniversalMetric(value, { isMonetary: !!money }),
  };
}

export function formatAxisValue(value: number, isMonetary: boolean = false, unit?: string): string {
  if (Number.isNaN(value)) return '0';
  const abs = Math.abs(value);
  let formatted: string;
  if (abs >= 1e9) formatted = `${(value / 1e9).toFixed(1)}B`;
  else if (abs >= 1e6) formatted = `${(value / 1e6).toFixed(1)}M`;
  else if (abs >= 1e4) formatted = `${(value / 1e3).toFixed(0)}K`;
  else formatted = Number.isInteger(value) ? value.toLocaleString('en-US') : value.toFixed(1);

  return isMoney({ isMonetary, unit }) ? `$${formatted}` : formatted;
}
