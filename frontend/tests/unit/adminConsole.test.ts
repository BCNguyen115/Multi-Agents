import { describe, expect, it } from 'vitest';
import type { AdminOverviewData } from '../../lib/adminApi';
import { dailyCostOption } from '../../lib/adminCharts';
import { ADMIN_NAV, NAV_GROUPS, attentionItems, auditParams, dayEnd, fillDays, effectivePolicy, fillGaps, formatAge, formatBytes, formatTime, isActiveNav, serviceState } from '../../lib/adminConsole';

const day = (value: string, cost = 1) => ({ day: value, calls: 1, tokens: 10, cost });

function overview(overrides: Partial<AdminOverviewData> = {}): AdminOverviewData {
  return {
    accounts: { total: 5, pending: 0, locked: 0, env: 1 },
    organization: { tenants: 1, departments: 1 },
    approvals_pending: 0,
    jobs: { queued: 0, running: 0, done_24h: 3, failed_24h: 0 },
    cost: { today: 0, week_total: 0, week_calls: 0, per_day: [] },
    content: { conversations: 0, dashboards: 0, documents: 0, feedback_up: 0, feedback_down: 0 },
    activity: [],
    ...overrides,
  };
}

describe('isActiveNav', () => {
  const [overviewItem, monitoring] = ADMIN_NAV;

  it('opens the front page only on /admin itself', () => {
    expect(isActiveNav('/admin', overviewItem)).toBe(true);
    expect(isActiveNav('/admin/', overviewItem)).toBe(true);
    expect(isActiveNav('/admin/monitoring', overviewItem)).toBe(false);
  });

  it('opens a section on its own route and below it, and nothing else', () => {
    expect(isActiveNav('/admin/monitoring', monitoring)).toBe(true);
    expect(isActiveNav('/admin/monitoring/', monitoring)).toBe(true);
    expect(isActiveNav('/admin/monitoring/x', monitoring)).toBe(true);
    expect(isActiveNav('/admin/monitoringfoo', monitoring)).toBe(false);
    expect(isActiveNav('/admin/accounts', monitoring)).toBe(false);
  });
});

describe('attentionItems', () => {
  it('is empty when nothing waits for an administrator', () => {
    expect(attentionItems(overview())).toEqual([]);
    expect(attentionItems(overview({ approvals_pending: null }))).toEqual([]); // Redis could not be asked: nothing is claimed
  });

  it('lists accounts to grant, approvals to decide and failed jobs, each with where to deal with it', () => {
    const items = attentionItems(
      overview({ accounts: { total: 5, pending: 2, locked: 0, env: 1 }, approvals_pending: 3, jobs: { queued: 0, running: 0, done_24h: 0, failed_24h: 4 } }),
    );
    expect(items).toEqual([
      { id: 'pending', count: 2, href: '/admin/accounts' },
      { id: 'approvals', count: 3, href: '/admin/approvals' },
      { id: 'jobs', count: 4, href: '/admin/monitoring' },
    ]);
  });
});

describe('formatAge', () => {
  it('reads in the two largest units, the same in both languages', () => {
    expect(formatAge(0)).toBe('0s');
    expect(formatAge(59)).toBe('59s');
    expect(formatAge(60)).toBe('1m');
    expect(formatAge(3661)).toBe('1h 1m');
    expect(formatAge(90061)).toBe('1d 1h');
  });

  it('never goes negative', () => {
    expect(formatAge(-5)).toBe('0s');
  });
});

describe('fillGaps', () => {
  it('puts a zero day in every quiet day between the first and the last', () => {
    const filled = fillGaps([day('2026-10-04', 4), day('2026-10-01', 1)]);
    expect(filled.map((d) => d.day)).toEqual(['2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04']);
    expect(filled.map((d) => d.cost)).toEqual([1, 0, 0, 4]);
  });

  it('crosses a month end and leaves a single day alone', () => {
    expect(fillGaps([day('2026-09-30'), day('2026-10-02')]).map((d) => d.day)).toEqual(['2026-09-30', '2026-10-01', '2026-10-02']);
    expect(fillGaps([day('2026-10-01')])).toEqual([day('2026-10-01')]);
    expect(fillGaps([])).toEqual([]);
  });
});

describe('serviceState', () => {
  it('tells up, off (not configured) and failing apart', () => {
    expect(serviceState('ok')).toBe('ok');
    expect(serviceState('off')).toBe('off');
    expect(serviceState('ConnectionError')).toBe('fail');
    expect(serviceState('TimeoutError')).toBe('fail');
  });
});

describe('dailyCostOption', () => {
  const theme = { palette: ['#1', '#2', '#3', '#4'], text: '#t', muted: '#m', grid: '#g', axis: '#a', surface: '#s', fg: '#f', positive: '#p', negative: '#n', font: 'sans' };
  const option = dailyCostOption([day('2026-10-01', 0.5), day('2026-10-02', 1.25)], theme, (n) => `$${n}`);

  it('draws the server numbers as one bar per day, labelled month-day', () => {
    expect(option.xAxis.data).toEqual(['10-01', '10-02']);
    expect(option.series[0].data).toEqual([0.5, 1.25]);
    expect(option.series[0].type).toBe('bar');
  });

  it('formats the axis and the tooltip with the given money format, and describes itself to screen readers', () => {
    expect(option.yAxis.axisLabel.formatter(2)).toBe('$2');
    expect(option.tooltip.valueFormatter(0.5)).toBe('$0.5');
    expect(option.aria.enabled).toBe(true);
  });
});

describe('the menu', () => {
  it('puts every entry in a known group and keeps the front page first, alone in its group', () => {
    const groups = new Set(NAV_GROUPS.map((g) => g.id));
    expect(ADMIN_NAV.every((item) => groups.has(item.group))).toBe(true);
    expect(ADMIN_NAV[0]).toMatchObject({ href: '/admin', group: 'overview' });
    expect(ADMIN_NAV.filter((item) => item.group === 'overview')).toHaveLength(1);
    expect(new Set(ADMIN_NAV.map((item) => item.href)).size).toBe(ADMIN_NAV.length);
  });
});

describe('auditParams', () => {
  it('leaves blank filters out and keeps the rest, trimmed', () => {
    expect(auditParams({})).toBe('');
    expect(auditParams({ actor: ' alice ', action: 'hitl.', tenant: '', q: '  ' })).toBe('?actor=alice&action=hitl.');
  });

  it('turns a date range into [start of the first day, start of the day after the last)', () => {
    expect(auditParams({ since: '2026-10-01', until: '2026-10-03' })).toBe('?since=2026-10-01T00%3A00%3A00&until=2026-10-04T00%3A00%3A00');
    expect(dayEnd('2026-12-31')).toBe('2027-01-01T00:00:00');
  });

  it('ignores a date that is not one and adds the paging fields', () => {
    expect(auditParams({ since: 'yesterday', until: '2026-13-40' })).toBe('');
    expect(auditParams({ outcome: 'denied' }, { limit: 50, before: 120 })).toBe('?outcome=denied&limit=50&before=120');
  });
});

describe('formatTime and formatBytes', () => {
  it('shows a dash for nothing or nonsense and a date otherwise', () => {
    expect(formatTime(null, 'vi')).toBe('–');
    expect(formatTime('not a date', 'en')).toBe('–');
    expect(formatTime('2026-10-08T07:42:00Z', 'en')).toMatch(/2026/);
  });

  it('counts in 1024s with one decimal from the kilobyte up', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(1023)).toBe('1023 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
    expect(formatBytes(3 * 1024 ** 4)).toBe('3.0 TB');
  });
});

describe('fillDays', () => {
  it('fills any per-day series with the blank the caller gives', () => {
    const filled = fillDays([{ day: '2026-10-01', up: 2, down: 1 }, { day: '2026-10-03', up: 1, down: 0 }], (day) => ({ day, up: 0, down: 0 }));
    expect(filled).toEqual([{ day: '2026-10-01', up: 2, down: 1 }, { day: '2026-10-02', up: 0, down: 0 }, { day: '2026-10-03', up: 1, down: 0 }]);
  });
});

describe('effectivePolicy', () => {
  const policies = [
    { tenant_id: 'acme', department_id: '*', allowed_agents: ['rag_agent', 'search_agent'], can_upload_knowledge: false },
    { tenant_id: 'acme', department_id: 'legal', allowed_agents: null, can_upload_knowledge: true },
    { tenant_id: 'acme', department_id: 'hr', allowed_agents: ['db_agent'], can_upload_knowledge: null },
  ];

  it('takes each field from the department, else from the tenant default, else nothing', () => {
    expect(effectivePolicy(policies, 'acme', 'legal')).toEqual({ agents: ['rag_agent', 'search_agent'], agentsFrom: 'tenant', upload: true, uploadFrom: 'department' });
    expect(effectivePolicy(policies, 'acme', 'hr')).toEqual({ agents: ['db_agent'], agentsFrom: 'department', upload: false, uploadFrom: 'tenant' });
    expect(effectivePolicy(policies, 'acme', 'unlisted')).toEqual({ agents: ['rag_agent', 'search_agent'], agentsFrom: 'tenant', upload: false, uploadFrom: 'tenant' });
    expect(effectivePolicy(policies, 'other', 'x')).toEqual({ agents: null, agentsFrom: 'none', upload: null, uploadFrom: 'none' });
  });

  it('reads the tenant default row as itself', () => {
    expect(effectivePolicy(policies, 'acme', '*')).toEqual({ agents: ['rag_agent', 'search_agent'], agentsFrom: 'tenant', upload: false, uploadFrom: 'tenant' });
  });
});
