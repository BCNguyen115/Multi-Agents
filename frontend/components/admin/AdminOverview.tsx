'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import ReactECharts from 'echarts-for-react';
import { Loader2 } from 'lucide-react';
import { AdminFacts } from './AdminFacts';
import { AdminPageHeader } from './AdminPageHeader';
import { AdminStat } from './AdminStat';
import { readTheme } from '../dashboard/EChartComponent';
import { formatUsd, getOverview, type AdminOverviewData, type CostDay } from '../../lib/adminApi';
import { dailyCostOption } from '../../lib/adminCharts';
import { attentionItems, fillGaps } from '../../lib/adminConsole';
import { t, useLang, type MessageKey } from '../../lib/i18n';
import { useIsDark } from '../../lib/useIsDark';

const number = (value: number) => value.toLocaleString('en-US');

function CostChart({ days }: { days: CostDay[] }) {
  const isDark = useIsDark();
  const option = useMemo(() => dailyCostOption(fillGaps(days), readTheme(isDark), formatUsd), [days, isDark]);
  return <ReactECharts option={option} style={{ height: 220 }} opts={{ renderer: 'svg' }} notMerge />;
}

/** The console's front page: the four numbers that matter, what waits for an administrator, seven days of cost, the latest activity. */
export const AdminOverview: React.FC = () => {
  const [lang] = useLang();
  const [data, setData] = useState<AdminOverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    getOverview()
      .then((overview) => current && setData(overview))
      .catch((e: unknown) => current && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      current = false;
    };
  }, []);

  const when = (iso: string) => new Date(iso).toLocaleString(lang === 'vi' ? 'vi-VN' : 'en-GB');
  const header = <AdminPageHeader title={t(lang, 'admin.overview.title')} description={t(lang, 'admin.overview.subtitle')} />;

  if (error) {
    return (
      <div className="space-y-6">
        {header}
        <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.overview.loadFailed', { error })}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="space-y-6">
        {header}
        <div className="flex items-center gap-2 text-sm text-foreground-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'admin.overview.loading')}
        </div>
      </div>
    );
  }

  const attention = attentionItems(data);
  const content: [string, string][] = [
    [t(lang, 'admin.overview.org'), t(lang, 'admin.overview.orgValue', { tenants: data.organization.tenants, departments: data.organization.departments })],
    [t(lang, 'admin.overview.conversations'), number(data.content.conversations)],
    [t(lang, 'admin.overview.dashboards'), number(data.content.dashboards)],
    [t(lang, 'admin.overview.documents'), number(data.content.documents)],
    [t(lang, 'admin.overview.feedback'), t(lang, 'admin.overview.feedbackValue', { up: data.content.feedback_up, down: data.content.feedback_down })],
  ];

  return (
    <div className="space-y-6" data-testid="admin-overview">
      {header}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <AdminStat
          label={t(lang, 'admin.overview.accounts')}
          value={number(data.accounts.total)}
          hint={t(lang, 'admin.overview.accountsHint', { pending: data.accounts.pending, locked: data.accounts.locked })}
          href="/admin/accounts"
        />
        <AdminStat
          label={t(lang, 'admin.overview.approvals')}
          value={data.approvals_pending === null ? '–' : number(data.approvals_pending)}
          hint={data.approvals_pending === null ? t(lang, 'admin.overview.unavailable') : t(lang, 'admin.overview.approvalsHint')}
        />
        <AdminStat
          label={t(lang, 'admin.overview.jobs')}
          value={number(data.jobs.failed_24h)}
          hint={t(lang, 'admin.overview.jobsHint', { queued: data.jobs.queued, running: data.jobs.running })}
          tone={data.jobs.failed_24h > 0 ? 'alert' : 'neutral'}
          href="/admin/monitoring"
        />
        <AdminStat
          label={t(lang, 'admin.overview.costToday')}
          value={formatUsd(data.cost.today)}
          hint={t(lang, 'admin.overview.costHint', { week: formatUsd(data.cost.week_total) })}
          href="/admin/costs"
        />
      </div>

      <section aria-labelledby="admin-attention" className="space-y-2">
        <h2 id="admin-attention" className="text-lg font-bold text-foreground">{t(lang, 'admin.overview.attention')}</h2>
        {attention.length === 0 ? (
          <p className="text-sm text-foreground-secondary">{t(lang, 'admin.overview.allClear')}</p>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {attention.map((item) => {
              const text = t(lang, `admin.overview.attention.${item.id}` as MessageKey, { count: item.count });
              return (
                <li key={item.id} className="px-4 py-3 text-sm">
                  {item.href ? (
                    <Link href={item.href} className="font-medium text-accent-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary">
                      {text}
                    </Link>
                  ) : (
                    <span className="text-foreground">{text}</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <section aria-labelledby="admin-cost-chart" className="min-w-0 space-y-2">
          <h2 id="admin-cost-chart" className="text-lg font-bold text-foreground">{t(lang, 'admin.overview.chart')}</h2>
          <div className="rounded-lg border border-border bg-surface p-3">
            {data.cost.per_day.length === 0 ? <p className="py-8 text-center text-sm text-foreground-secondary">{t(lang, 'admin.overview.chartEmpty')}</p> : <CostChart days={data.cost.per_day} />}
          </div>
        </section>

        <section aria-labelledby="admin-activity" className="min-w-0 space-y-2">
          <h2 id="admin-activity" className="text-lg font-bold text-foreground">{t(lang, 'admin.overview.activity')}</h2>
          {data.activity.length === 0 ? (
            <p className="text-sm text-foreground-secondary">{t(lang, 'admin.overview.activityEmpty')}</p>
          ) : (
            <ul className="divide-y divide-border rounded-lg border border-border">
              {data.activity.map((row, index) => (
                <li key={`${row.at}-${index}`} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 px-3 py-2 text-xs">
                  <span className="min-w-0 break-words">
                    <span className="font-mono text-foreground">{row.action}</span>
                    <span className="text-foreground-muted"> · {row.actor}{row.target ? ` → ${row.target}` : ''}</span>
                  </span>
                  <time dateTime={row.at} className="tabular-nums text-foreground-muted">{when(row.at)}</time>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section aria-labelledby="admin-content" className="space-y-2">
        <h2 id="admin-content" className="text-lg font-bold text-foreground">{t(lang, 'admin.overview.content')}</h2>
        <AdminFacts rows={content} />
      </section>
    </div>
  );
};
