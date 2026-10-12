'use client';

import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { formatUsd, getOrg, getUsageReport, type OrgTenant, type UsageReport } from '../../lib/adminApi';
import { t, useLang, type MessageKey } from '../../lib/i18n';

const RANGES = [7, 30, 90];

type Column<T> = { label: MessageKey; cell: (row: T) => React.ReactNode; numeric?: boolean };

function Table<T>({ title, rows, columns, rowKey }: { title: MessageKey; rows: T[]; columns: Column<T>[]; rowKey: (row: T) => string }) {
  const [lang] = useLang();
  if (rows.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <h2 className="text-lg font-bold text-foreground">{t(lang, title)}</h2>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-raised text-foreground-muted">
            <tr>
              {columns.map((c) => (
                <th key={c.label} scope="col" className={`px-3 py-2 font-semibold ${c.numeric ? 'text-right' : ''}`}>{t(lang, c.label)}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((row) => (
              <tr key={rowKey(row)} className="hover:bg-surface-raised/50">
                {columns.map((c) => (
                  <td key={c.label} className={`px-3 py-2 ${c.numeric ? 'text-right tabular-nums' : ''}`}>{c.cell(row)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** What the LLM calls cost, by user, tenant, model and day (from `usage_events`; the figures are LiteLLM's estimates). */
export const AdminUsage: React.FC = () => {
  const [lang] = useLang();
  const [days, setDays] = useState(30);
  const [tenant, setTenant] = useState('');
  const [tenants, setTenants] = useState<OrgTenant[]>([]);
  const [report, setReport] = useState<UsageReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getOrg().then(setTenants).catch(() => setTenants([])); // the filter is an extra: the report works without its options
  }, []);

  useEffect(() => {
    let current = true;
    setReport(null);
    getUsageReport(days, tenant || undefined)
      .then((r) => {
        if (current) {
          setReport(r);
          setError(null);
        }
      })
      .catch((e: unknown) => current && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      current = false;
    };
  }, [days, tenant]);

  const calls = (r: { calls: number }) => r.calls.toLocaleString('en-US');
  const tokens = (r: { tokens: number }) => r.tokens.toLocaleString('en-US');
  const cost = (r: { cost: number }) => formatUsd(r.cost);

  return (
    <section aria-label={t(lang, 'usage.title')} className="space-y-4" data-testid="admin-usage">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <label className="flex items-center gap-2 text-xs text-foreground-secondary">
          {t(lang, 'admin.costs.tenant')}
          <select value={tenant} onChange={(e) => setTenant(e.target.value)} className="rounded-md border border-border-input bg-surface px-2 py-1 text-base sm:text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary">
            <option value="">{t(lang, 'admin.costs.allTenants')}</option>
            {tenants.map((o) => (
              <option key={o.id} value={o.id}>{o.name || o.id}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs text-foreground-secondary">
          {t(lang, 'usage.range')}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded-md border border-border-input bg-surface px-2 py-1 text-base sm:text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary">
            {RANGES.map((d) => (
              <option key={d} value={d}>{t(lang, 'usage.days', { days: d })}</option>
            ))}
          </select>
        </label>
      </div>
      {error && <p role="alert" className="text-sm text-accent-error">{t(lang, 'usage.loadFailed', { error })}</p>}
      {!error && !report && (
        <div className="flex items-center gap-2 text-sm text-foreground-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'usage.loading')}
        </div>
      )}
      {report && report.totals.calls === 0 && <p className="text-sm text-foreground-secondary">{t(lang, 'usage.empty')}</p>}
      {report && report.totals.calls > 0 && (
        <div className="space-y-4">
          <p className="text-sm font-semibold text-foreground">{t(lang, 'usage.totals', { calls: calls(report.totals), tokens: tokens(report.totals), cost: cost(report.totals) })}</p>
          <p className="text-xs text-foreground-muted">
            {report.budget_usd_per_user_day
              ? t(lang, report.budget_hard ? 'usage.budgetHard' : 'usage.budget', { amount: formatUsd(report.budget_usd_per_user_day) })
              : t(lang, 'usage.noBudget')}
          </p>
          <Table
            title="usage.byUser"
            rows={report.users}
            rowKey={(r) => `${r.tenant_id}/${r.user_id}`}
            columns={[
              { label: 'usage.colUser', cell: (r) => <span className="font-medium text-foreground">{r.user_id}{r.over_budget && <span className="ml-2 font-semibold text-accent-error">{t(lang, 'usage.over')}</span>}</span> },
              { label: 'usage.colTenant', cell: (r) => r.tenant_id || '–' },
              { label: 'usage.colCalls', cell: calls, numeric: true },
              { label: 'usage.colTokens', cell: tokens, numeric: true },
              { label: 'usage.colToday', cell: (r) => formatUsd(r.today), numeric: true },
              { label: 'usage.colCost', cell: cost, numeric: true },
            ]}
          />
          <Table
            title="usage.byTenant"
            rows={report.tenants}
            rowKey={(r) => r.tenant_id}
            columns={[
              { label: 'usage.colTenant', cell: (r) => r.tenant_id || '–' },
              { label: 'usage.colCalls', cell: calls, numeric: true },
              { label: 'usage.colTokens', cell: tokens, numeric: true },
              { label: 'usage.colCost', cell: cost, numeric: true },
            ]}
          />
          <Table
            title="usage.byModel"
            rows={report.models}
            rowKey={(r) => r.model}
            columns={[
              { label: 'usage.colModel', cell: (r) => r.model || '–' },
              { label: 'usage.colCalls', cell: calls, numeric: true },
              { label: 'usage.colTokens', cell: tokens, numeric: true },
              { label: 'usage.colCost', cell: cost, numeric: true },
            ]}
          />
          <Table
            title="usage.byAgent"
            rows={report.agents}
            rowKey={(r) => r.agent}
            columns={[
              { label: 'usage.colAgent', cell: (r) => <span className="font-mono">{r.agent}</span> },
              { label: 'usage.colCalls', cell: calls, numeric: true },
              { label: 'usage.colTokens', cell: tokens, numeric: true },
              { label: 'usage.colRetryCost', cell: (r) => formatUsd(r.retry_cost), numeric: true },
              { label: 'usage.colCost', cell: cost, numeric: true },
            ]}
          />
          <Table
            title="usage.byStep"
            rows={report.nodes}
            rowKey={(r) => r.node}
            columns={[
              { label: 'usage.colStep', cell: (r) => <span className="font-mono">{r.node}</span> },
              { label: 'usage.colCalls', cell: calls, numeric: true },
              { label: 'usage.colTokens', cell: tokens, numeric: true },
              { label: 'usage.colCost', cell: cost, numeric: true },
            ]}
          />
          <Table
            title="usage.byDay"
            rows={[...report.per_day].reverse()}
            rowKey={(r) => r.day}
            columns={[
              { label: 'usage.colDay', cell: (r) => r.day },
              { label: 'usage.colCalls', cell: calls, numeric: true },
              { label: 'usage.colTokens', cell: tokens, numeric: true },
              { label: 'usage.colCost', cell: cost, numeric: true },
            ]}
          />
        </div>
      )}
    </section>
  );
};
