/** Pure rules of the administration console: the menu, which entry is open, what needs attention, how ages and gaps read. */

import type { AdminOverviewData, AuditFilter, CostDay, DepartmentPolicy } from './adminApi';
import type { Lang, MessageKey } from './i18n';

export type NavGroup = 'overview' | 'system' | 'manage' | 'insight';

export interface AdminNavItem {
  href: string;
  label: MessageKey;
  group: NavGroup;
  /** The front page matches only itself; the others also match what is below them. */
  exact?: boolean;
}

export const ADMIN_NAV: AdminNavItem[] = [
  { href: '/admin', label: 'admin.nav.overview', group: 'overview', exact: true },
  { href: '/admin/monitoring', label: 'admin.nav.monitoring', group: 'system' },
  { href: '/admin/operations', label: 'admin.nav.operations', group: 'system' },
  { href: '/admin/audit', label: 'admin.nav.audit', group: 'system' },
  { href: '/admin/accounts', label: 'admin.nav.accounts', group: 'manage' },
  { href: '/admin/organization', label: 'admin.nav.organization', group: 'manage' },
  { href: '/admin/knowledge', label: 'admin.nav.knowledge', group: 'manage' },
  { href: '/admin/approvals', label: 'admin.nav.approvals', group: 'manage' },
  { href: '/admin/costs', label: 'admin.nav.costs', group: 'insight' },
  { href: '/admin/quality', label: 'admin.nav.quality', group: 'insight' },
];

/** The headings of the menu; the group of the front page has none. */
export const NAV_GROUPS: { id: NavGroup; label: MessageKey | null }[] = [
  { id: 'overview', label: null },
  { id: 'system', label: 'admin.navGroup.system' },
  { id: 'manage', label: 'admin.navGroup.manage' },
  { id: 'insight', label: 'admin.navGroup.insight' },
];

export function isActiveNav(pathname: string, item: AdminNavItem): boolean {
  const path = pathname.replace(/\/+$/, '') || '/';
  return item.exact ? path === item.href : path === item.href || path.startsWith(`${item.href}/`);
}

export interface Attention {
  id: 'pending' | 'approvals' | 'jobs';
  count: number;
  /** Where to deal with it. */
  href?: string;
}

/** What waits for an administrator right now. Empty when nothing does: the front page then shows no "needs attention" block. */
export function attentionItems(overview: AdminOverviewData): Attention[] {
  const items: Attention[] = [];
  if (overview.accounts.pending > 0) items.push({ id: 'pending', count: overview.accounts.pending, href: '/admin/accounts' });
  if ((overview.approvals_pending ?? 0) > 0) items.push({ id: 'approvals', count: overview.approvals_pending as number, href: '/admin/approvals' });
  if (overview.jobs.failed_24h > 0) items.push({ id: 'jobs', count: overview.jobs.failed_24h, href: '/admin/monitoring' });
  return items;
}

/** `45s`, `5m`, `2h 3m`, `1d 4h`: the same in both languages. */
export function formatAge(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3_600);
  const minutes = Math.floor((total % 3_600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m`;
  return `${total}s`;
}

/** The days between the first and the last one that have calls, with zeros for the quiet ones, so the bars keep their spacing. */
export function fillDays<T extends { day: string }>(days: T[], blank: (day: string) => T): T[] {
  if (days.length < 2) return days;
  const known = new Map(days.map((d) => [d.day, d]));
  const ordered = days.map((d) => d.day).sort();
  const last = Date.parse(`${ordered[ordered.length - 1]}T00:00:00Z`);
  const filled: T[] = [];
  for (let time = Date.parse(`${ordered[0]}T00:00:00Z`); time <= last; time += 86_400_000) {
    const day = new Date(time).toISOString().slice(0, 10);
    filled.push(known.get(day) ?? blank(day));
  }
  return filled;
}

export const fillGaps = (days: CostDay[]): CostDay[] => fillDays(days, (day) => ({ day, calls: 0, tokens: 0, cost: 0 }));

export type ServiceState = 'ok' | 'off' | 'fail';

export function serviceState(status: string): ServiceState {
  return status === 'ok' ? 'ok' : status === 'off' ? 'off' : 'fail';
}

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const validDay = (day: string | undefined): day is string => !!day && DAY.test(day) && !Number.isNaN(Date.parse(`${day}T00:00:00Z`));

/** `YYYY-MM-DD` of a date input → the start of that day, which is what the backend's `since` compares with. */
export const dayStart = (day: string): string => `${day}T00:00:00`;

/** The same day for `until`: the start of the NEXT one (the backend's `until` is exclusive), so the day itself is included. */
export function dayEnd(day: string): string {
  return new Date(Date.parse(`${day}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 19);
}

/** The query string of the audit viewer and its CSV export: blank filters are left out, a malformed date is ignored. */
export function auditParams(filter: AuditFilter, extra: Record<string, string | number | undefined> = {}): string {
  const params = new URLSearchParams();
  const put = (key: string, value: string | number | undefined) => {
    const text = typeof value === 'string' ? value.trim() : value;
    if (text !== undefined && text !== '') params.set(key, String(text));
  };
  put('actor', filter.actor);
  put('action', filter.action);
  put('tenant', filter.tenant);
  put('outcome', filter.outcome);
  put('q', filter.q);
  if (validDay(filter.since)) params.set('since', dayStart(filter.since));
  if (validDay(filter.until)) params.set('until', dayEnd(filter.until));
  for (const [key, value] of Object.entries(extra)) put(key, value);
  const text = params.toString();
  return text ? `?${text}` : '';
}

/** A time as the administrator reads it in the language of the interface; `–` when there is none. */
export function formatTime(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return '–';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '–' : date.toLocaleString(lang === 'vi' ? 'vi-VN' : 'en-GB');
}

/** `12 B`, `3.4 KB`, `5.0 MB`: for backup sizes. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${Math.max(0, Math.floor(bytes))} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

export type PolicySource = 'department' | 'tenant' | 'none';

export interface EffectivePolicy {
  /** `null` = every agent. */
  agents: string[] | null;
  agentsFrom: PolicySource;
  /** `null` = decided by the account's role. */
  upload: boolean | null;
  uploadFrom: PolicySource;
}

/** What a department really gets, field by field: its own value, else its tenant's default (`*`), else no restriction. Mirrors `policy.merge` in the backend. */
export function effectivePolicy(policies: DepartmentPolicy[], tenantId: string, departmentId: string): EffectivePolicy {
  const own = departmentId === '*' ? undefined : policies.find((p) => p.tenant_id === tenantId && p.department_id === departmentId);
  const tenant = policies.find((p) => p.tenant_id === tenantId && p.department_id === '*');
  const pick = <T,>(field: 'allowed_agents' | 'can_upload_knowledge'): [T | null, PolicySource] => {
    if (own && own[field] !== null && own[field] !== undefined) return [own[field] as T, 'department'];
    if (tenant && tenant[field] !== null && tenant[field] !== undefined) return [tenant[field] as T, 'tenant'];
    return [null, 'none'];
  };
  const [agents, agentsFrom] = pick<string[]>('allowed_agents');
  const [upload, uploadFrom] = pick<boolean>('can_upload_knowledge');
  return { agents, agentsFrom, upload, uploadFrom };
}
