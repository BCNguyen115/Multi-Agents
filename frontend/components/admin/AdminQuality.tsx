'use client';

import React, { useCallback, useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react';
import { Loader2 } from 'lucide-react';
import { AdminStat } from './AdminStat';
import { AdminTable, type Column } from './AdminTable';
import { readTheme } from '../dashboard/EChartComponent';
import { getFeedback, getOrg, type FeedbackReport } from '../../lib/adminApi';
import { feedbackOption } from '../../lib/adminCharts';
import { fillDays, formatTime } from '../../lib/adminConsole';
import { t, useLang, type MessageKey } from '../../lib/i18n';
import { useAdminData } from '../../lib/useAdminData';
import { useIsDark } from '../../lib/useIsDark';

const RANGES = [7, 30, 90];
const FIELD =
  'rounded-md border border-border-input bg-surface px-2 py-1 text-base sm:text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary';

type Down = FeedbackReport['recent_down'][number];
type TenantRow = FeedbackReport['tenants'][number];
type AgentRow = FeedbackReport['agents'][number];
type ReasonRow = FeedbackReport['reasons'][number];
type ReviewAgent = FeedbackReport['reviews']['agents'][number];
type ReviewLow = FeedbackReport['reviews']['recent_low'][number];

function FeedbackChart({ report }: { report: FeedbackReport }) {
  const [lang] = useLang();
  const isDark = useIsDark();
  const option = useMemo(
    () => feedbackOption(fillDays(report.per_day, (day) => ({ day, up: 0, down: 0 })), readTheme(isDark), { up: t(lang, 'admin.quality.up'), down: t(lang, 'admin.quality.down') }),
    [report, isDark, lang],
  );
  return <ReactECharts option={option} style={{ height: 240 }} opts={{ renderer: 'svg' }} notMerge />;
}

/** What users thought of the answers: how many found them helpful, when, in which tenant, and the latest ones they did not. */
export const AdminQuality: React.FC = () => {
  const [lang] = useLang();
  const [days, setDays] = useState(30);
  const [tenant, setTenant] = useState('');
  const fetcher = useCallback(() => getFeedback(days, tenant || undefined), [days, tenant]);
  const orgFetcher = useCallback(() => getOrg(), []);
  const { data, error } = useAdminData(fetcher);
  const org = useAdminData(orgFetcher);

  const downColumns: Column<Down>[] = [
    { key: 'when', label: t(lang, 'admin.quality.colWhen'), cell: (r) => formatTime(r.at, lang), className: 'whitespace-nowrap tabular-nums text-foreground-muted' },
    { key: 'user', label: t(lang, 'admin.quality.colUser'), cell: (r) => r.user_id, className: 'font-medium text-foreground' },
    { key: 'tenant', label: t(lang, 'admin.quality.colTenant'), cell: (r) => r.tenant_id || '–', className: 'text-foreground-secondary' },
    { key: 'agent', label: t(lang, 'admin.quality.colAgent'), cell: (r) => (r.agent ? <span className="font-mono">{r.agent}</span> : t(lang, 'admin.quality.noAgent')), className: 'text-foreground-secondary' },
    { key: 'query', label: t(lang, 'admin.quality.colQuestion'), cell: (r) => r.query || '–', className: 'min-w-[14rem] break-words text-foreground' },
    {
      key: 'answer',
      label: t(lang, 'admin.quality.colAnswer'),
      cell: (r) => (r.answer ? (
        <details>
          <summary className="cursor-pointer text-accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary">{t(lang, 'admin.audit.showDetail')}</summary>
          <p className="mt-1 max-w-sm whitespace-pre-wrap break-words text-foreground-secondary">{r.answer}</p>
        </details>
      ) : '–'),
    },
    {
      key: 'verdict',
      label: t(lang, 'admin.quality.colVerdict'),
      cell: (r) => (r.verified === null ? '–' : (
        <span className={r.verified ? '' : 'text-accent-error'}>
          {t(lang, r.verified ? 'admin.quality.verdictPassed' : 'admin.quality.verdictNotPassed')}
          {r.retries > 0 && ` · ${t(lang, 'admin.quality.verdictRetries', { count: r.retries })}`}
        </span>
      )),
      className: 'whitespace-nowrap',
    },
    { key: 'reasons', label: t(lang, 'admin.quality.colReasons'), cell: (r) => (r.reasons.length ? r.reasons.map((x) => t(lang, `feedback.reason.${x}` as MessageKey)).join(', ') : '–'), className: 'break-words text-foreground-secondary' },
    { key: 'comment', label: t(lang, 'admin.quality.colComment'), cell: (r) => r.comment || '–', className: 'break-words text-foreground-secondary' },
  ];
  const agentColumns: Column<AgentRow>[] = [
    { key: 'agent', label: t(lang, 'admin.quality.colAgent'), cell: (r) => (r.agent ? <span className="font-mono">{r.agent}</span> : t(lang, 'admin.quality.noAgent')), className: 'font-medium text-foreground' },
    { key: 'up', label: t(lang, 'admin.quality.up'), cell: (r) => r.up, numeric: true },
    { key: 'down', label: t(lang, 'admin.quality.down'), cell: (r) => <span className={r.down > 0 ? 'text-accent-error' : ''}>{r.down}</span>, numeric: true },
  ];
  const reasonColumns: Column<ReasonRow>[] = [
    { key: 'reason', label: t(lang, 'admin.quality.colReasons'), cell: (r) => t(lang, `feedback.reason.${r.reason}` as MessageKey), className: 'font-medium text-foreground' },
    { key: 'count', label: t(lang, 'admin.quality.colCount'), cell: (r) => r.count, numeric: true },
  ];
  const tenantColumns: Column<TenantRow>[] = [
    { key: 'tenant', label: t(lang, 'admin.quality.colTenant'), cell: (r) => r.tenant_id || '–', className: 'font-medium text-foreground' },
    { key: 'up', label: t(lang, 'admin.quality.up'), cell: (r) => r.up, numeric: true },
    { key: 'down', label: t(lang, 'admin.quality.down'), cell: (r) => <span className={r.down > 0 ? 'text-accent-error' : ''}>{r.down}</span>, numeric: true },
  ];

  const reviewAgentColumns: Column<ReviewAgent>[] = [
    { key: 'agent', label: t(lang, 'admin.quality.colAgent'), cell: (r) => (r.agent ? <span className="font-mono">{r.agent}</span> : t(lang, 'admin.quality.noAgent')), className: 'font-medium text-foreground' },
    { key: 'graded', label: t(lang, 'admin.quality.reviewsGraded'), cell: (r) => r.graded, numeric: true },
    { key: 'average', label: t(lang, 'admin.quality.reviewsAverage'), cell: (r) => (r.average === null ? '–' : r.average.toFixed(2)), numeric: true },
  ];
  const reviewLowColumns: Column<ReviewLow>[] = [
    { key: 'when', label: t(lang, 'admin.quality.colWhen'), cell: (r) => formatTime(r.at, lang), className: 'whitespace-nowrap tabular-nums text-foreground-muted' },
    { key: 'agent', label: t(lang, 'admin.quality.colAgent'), cell: (r) => <span className="font-mono">{r.agent || '–'}</span>, className: 'text-foreground-secondary' },
    { key: 'score', label: t(lang, 'admin.quality.colScore'), cell: (r) => <span className="text-accent-error">{r.score}</span>, numeric: true },
    { key: 'query', label: t(lang, 'admin.quality.colQuestion'), cell: (r) => r.query || '–', className: 'min-w-[14rem] break-words text-foreground' },
    {
      key: 'answer',
      label: t(lang, 'admin.quality.colAnswer'),
      cell: (r) => (r.answer ? (
        <details>
          <summary className="cursor-pointer text-accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary">{t(lang, 'admin.audit.showDetail')}</summary>
          <p className="mt-1 max-w-sm whitespace-pre-wrap break-words text-foreground-secondary">{r.answer}</p>
        </details>
      ) : '–'),
    },
    { key: 'reason', label: t(lang, 'admin.quality.colGraderReason'), cell: (r) => r.reason || '–', className: 'break-words text-foreground-secondary' },
  ];

  const total = data ? data.up + data.down : 0;
  return (
    <section aria-label={t(lang, 'admin.quality.title')} className="space-y-4" data-testid="admin-quality">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <label className="flex items-center gap-2 text-xs text-foreground-secondary">
          {t(lang, 'admin.costs.tenant')}
          <select value={tenant} onChange={(e) => setTenant(e.target.value)} className={FIELD}>
            <option value="">{t(lang, 'admin.costs.allTenants')}</option>
            {(org.data ?? []).map((o) => <option key={o.id} value={o.id}>{o.name || o.id}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs text-foreground-secondary">
          {t(lang, 'usage.range')}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className={FIELD}>
            {RANGES.map((d) => <option key={d} value={d}>{t(lang, 'usage.days', { days: d })}</option>)}
          </select>
        </label>
      </div>

      {error && <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.quality.loadFailed', { error })}</p>}
      {!data && !error && (
        <div className="flex items-center gap-2 text-sm text-foreground-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'admin.quality.loading')}
        </div>
      )}

      {data && total === 0 && <p className="text-sm text-foreground-secondary">{t(lang, 'admin.quality.noData')}</p>}
      {data && total > 0 && (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <AdminStat label={t(lang, 'admin.quality.satisfaction')} value={data.satisfaction === null ? '–' : `${Math.round(data.satisfaction * 100)}%`} />
            <AdminStat label={t(lang, 'admin.quality.up')} value={data.up.toLocaleString('en-US')} />
            <AdminStat label={t(lang, 'admin.quality.down')} value={data.down.toLocaleString('en-US')} tone={data.down > 0 ? 'alert' : 'neutral'} />
          </div>

          <section aria-labelledby="quality-chart" className="space-y-2">
            <h2 id="quality-chart" className="text-lg font-bold text-foreground">{t(lang, 'admin.quality.perDay')}</h2>
            <div className="rounded-lg border border-border bg-surface p-3">
              <FeedbackChart report={data} />
            </div>
          </section>

          {data.tenants.length > 1 && (
            <section aria-labelledby="quality-tenants" className="space-y-2">
              <h2 id="quality-tenants" className="text-lg font-bold text-foreground">{t(lang, 'admin.quality.byTenant')}</h2>
              <AdminTable columns={tenantColumns} rows={data.tenants} rowKey={(r) => r.tenant_id} label={t(lang, 'admin.quality.byTenant')} />
            </section>
          )}

          {(data.agents.length > 0 || data.reasons.length > 0) && (
            <div className="grid gap-6 lg:grid-cols-2">
              {data.agents.length > 0 && (
                <section aria-labelledby="quality-agents" className="min-w-0 space-y-2">
                  <h2 id="quality-agents" className="text-lg font-bold text-foreground">{t(lang, 'admin.quality.byAgent')}</h2>
                  <AdminTable columns={agentColumns} rows={data.agents} rowKey={(r) => r.agent || '-'} label={t(lang, 'admin.quality.byAgent')} />
                </section>
              )}
              {data.reasons.length > 0 && (
                <section aria-labelledby="quality-reasons" className="min-w-0 space-y-2">
                  <h2 id="quality-reasons" className="text-lg font-bold text-foreground">{t(lang, 'admin.quality.reasons')}</h2>
                  <AdminTable columns={reasonColumns} rows={data.reasons} rowKey={(r) => r.reason} label={t(lang, 'admin.quality.reasons')} />
                </section>
              )}
            </div>
          )}

          <section aria-labelledby="quality-down" className="space-y-2">
            <h2 id="quality-down" className="text-lg font-bold text-foreground">{t(lang, 'admin.quality.recentDown')}</h2>
            <AdminTable columns={downColumns} rows={data.recent_down} rowKey={(r) => `${r.at}-${r.user_id}-${r.query}-${r.run_id}`} empty={t(lang, 'admin.quality.noData')} label={t(lang, 'admin.quality.recentDown')} />
          </section>
        </>
      )}

      {data && (
        <section aria-labelledby="quality-reviews" className="space-y-3" data-testid="admin-quality-reviews">
          <div>
            <h2 id="quality-reviews" className="text-lg font-bold text-foreground">{t(lang, 'admin.quality.reviewsTitle')}</h2>
            <p className="text-xs text-foreground-muted">{t(lang, 'admin.quality.reviewsHint', { rate: Math.round(data.reviews.sample_rate * 1000) / 10 })}</p>
          </div>
          {data.reviews.graded === 0 ? (
            <p className="text-sm text-foreground-secondary">{t(lang, 'admin.quality.reviewsNone')}</p>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <AdminStat label={t(lang, 'admin.quality.reviewsGraded')} value={data.reviews.graded.toLocaleString('en-US')} />
                <AdminStat label={t(lang, 'admin.quality.reviewsAverage')} value={data.reviews.average === null ? '–' : data.reviews.average.toFixed(2)} />
                <AdminStat label={t(lang, 'admin.quality.reviewsLow')} value={data.reviews.low.toLocaleString('en-US')} tone={data.reviews.low > 0 ? 'alert' : 'neutral'} />
              </div>
              <AdminTable columns={reviewAgentColumns} rows={data.reviews.agents} rowKey={(r) => r.agent || '-'} label={t(lang, 'admin.quality.reviewsByAgent')} />
              <h3 className="text-sm font-semibold text-foreground">{t(lang, 'admin.quality.reviewsLowList')}</h3>
              <AdminTable columns={reviewLowColumns} rows={data.reviews.recent_low} rowKey={(r) => `${r.at}-${r.agent}-${r.query}`} empty={t(lang, 'admin.quality.noData')} label={t(lang, 'admin.quality.reviewsLowList')} />
            </>
          )}
        </section>
      )}
    </section>
  );
};
