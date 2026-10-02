import { describe, expect, it } from 'vitest';
import { isDashboardSpecV2 } from '../../lib/dashboardApi';
import { MAX_STORED_TABLE_ROWS, sanitizeMessagesForStorage } from '../../lib/storage';
import type { ChatMessage } from '../../lib/types';

const v2 = {
  version: 2, language: 'vi', mode: 'dashboard', title: 't', fileName: 'f.csv', summaryText: '',
  story: { headline: 'h', sections: [], findings: [], actions: [], caveats: [], next_questions: [] },
  kpis: [], charts: [], slicers: [],
  table: { title: 't', columns: [], rows: [], totalRows: 0, truncated: false },
  analysis: { rows_total: 1, rows_used: 1, sampled: false, format: 'csv', notes: [], warnings: [] },
};

// What the previous version stored in the browser: no version/analysis/slicers/story
const v1 = { layout_type: 'full_dashboard', archetype: 'EXECUTIVE_STRATEGIC_OVERVIEW', kpis: [{ title: 'K', value: '1' }], charts: [{ title: 'C', type: 'bar', data: [] }], table: { rows: [{ a: 1 }] }, totalRows: 1 };

describe('isDashboardSpecV2', () => {
  it('accepts a complete v2 spec', () => {
    expect(isDashboardSpecV2(v2)).toBe(true);
  });

  it('rejects the old stored dashboard that crashed on `analysis.rows_used`', () => {
    expect(isDashboardSpecV2(v1)).toBe(false);
  });

  it('rejects malformed input without throwing', () => {
    for (const bad of [null, undefined, 'x', 42, {}, { ...v2, analysis: undefined }, { ...v2, charts: null }, { ...v2, table: { columns: [] } }, { ...v2, version: 1 }]) {
      expect(isDashboardSpecV2(bad)).toBe(false);
    }
  });
});

describe('sanitizeMessagesForStorage', () => {
  const message = (rows: number): ChatMessage => ({
    id: 'm', role: 'assistant', content: '',
    dashboardSpec: { ...v2, table: { ...v2.table, rows: Array.from({ length: rows }, (_, i) => ({ i })), totalRows: rows } } as never,
  });

  it('keeps small dashboards untouched (same object, no duplicated row copies)', () => {
    const map = { s: [message(10)] };
    const saved = sanitizeMessagesForStorage(map);
    expect(saved.s[0]).toBe(map.s[0]);
    expect(Object.keys(saved.s[0].dashboardSpec as object)).not.toContain('raw_data');
  });

  it('caps a large table once and says it was cut', () => {
    const saved = sanitizeMessagesForStorage({ s: [message(5000)] });
    const table = saved.s[0].dashboardSpec!.table;
    expect(table.rows).toHaveLength(MAX_STORED_TABLE_ROWS);
    expect(table.truncated).toBe(true);
    expect(JSON.stringify(saved).length).toBeLessThan(JSON.stringify({ s: [message(5000)] }).length / 2);
  });

  it('passes plain messages and legacy dashboards through without error', () => {
    const plain: ChatMessage = { id: 'p', role: 'user', content: 'hi' };
    const legacy = { id: 'l', role: 'assistant', content: '', dashboardSpec: v1 } as unknown as ChatMessage;
    expect(() => sanitizeMessagesForStorage({ s: [plain, legacy] })).not.toThrow();
  });
});
