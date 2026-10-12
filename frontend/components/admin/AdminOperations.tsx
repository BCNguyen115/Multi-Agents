'use client';

import React, { useCallback, useState } from 'react';
import { Loader2, XCircle } from 'lucide-react';
import { ConfirmDialog } from './AdminDialog';
import { AdminTable, type Column } from './AdminTable';
import { cancelJob, getConfig, getJobs, type AdminJob, type ConfigGroup } from '../../lib/adminApi';
import { formatTime } from '../../lib/adminConsole';
import { t, useLang, type Lang, type MessageKey } from '../../lib/i18n';
import { toast } from '../../lib/toast';
import { useAdminData } from '../../lib/useAdminData';

const REFRESH_MS = 15_000;
const STATUSES = ['', 'queued', 'running', 'done', 'failed'] as const;
const FIELD =
  'rounded-md border border-border-input bg-surface px-2 py-1.5 text-base sm:text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary';

/** A setting as an administrator reads it: switches as on/off, secrets as set/not set, lists joined, "no restriction" in words. */
function configValue(group: string, item: ConfigGroup['items'][number], lang: Lang): string {
  const { key, value } = item;
  if (typeof value === 'boolean') return t(lang, group === 'secrets' ? (value ? 'admin.ops.set' : 'admin.ops.unset') : value ? 'admin.ops.on' : 'admin.ops.off');
  if (value === null) return key === 'RAG_TENANT_IDS' ? t(lang, 'admin.ops.all') : '–';
  if (Array.isArray(value)) return value.length ? value.join(', ') : '–';
  if (typeof value === 'object') return Object.keys(value).length ? JSON.stringify(value) : '–';
  return value === '' ? '–' : String(value);
}

/** The background jobs (watch the queue, cancel one still waiting) and the configuration in force, read-only. */
export const AdminOperations: React.FC = () => {
  const [lang] = useLang();
  const [status, setStatus] = useState('');
  const jobsFetcher = useCallback(() => getJobs(status || undefined), [status]);
  const configFetcher = useCallback(() => getConfig(), []);
  const jobs = useAdminData(jobsFetcher, REFRESH_MS);
  const config = useAdminData(configFetcher);
  const [doomed, setDoomed] = useState<AdminJob | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const cancel = async () => {
    if (!doomed) return;
    setCancelling(true);
    try {
      await cancelJob(doomed.id);
      toast.success(t(lang, 'admin.ops.cancelled', { id: doomed.id }));
      setDoomed(null);
      await jobs.reload();
    } catch (e: unknown) {
      toast.error(t(lang, 'admin.ops.cancelFailed', { id: doomed.id, error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setCancelling(false);
    }
  };

  const columns: Column<AdminJob>[] = [
    { key: 'id', label: t(lang, 'admin.ops.colId'), cell: (j) => <span className="font-mono">{j.id}</span> },
    { key: 'kind', label: t(lang, 'admin.ops.colKind'), cell: (j) => <span className="font-mono">{j.kind}</span> },
    { key: 'user', label: t(lang, 'admin.ops.colUser'), cell: (j) => j.user_id || '–', className: 'text-foreground-secondary' },
    {
      key: 'status',
      label: t(lang, 'admin.ops.colStatus'),
      cell: (j) => <span className={j.status === 'failed' ? 'font-semibold text-accent-error' : ''}>{t(lang, `admin.ops.status.${j.status}` as MessageKey)}</span>,
    },
    { key: 'attempts', label: t(lang, 'admin.ops.colAttempts'), cell: (j) => j.attempts, numeric: true },
    { key: 'created', label: t(lang, 'admin.ops.colCreated'), cell: (j) => formatTime(j.created_at, lang), className: 'whitespace-nowrap tabular-nums text-foreground-muted' },
    { key: 'error', label: t(lang, 'admin.ops.colError'), cell: (j) => j.error || '–', className: 'break-words text-foreground-secondary' },
    {
      key: 'actions',
      label: '',
      className: 'whitespace-nowrap text-right',
      cell: (j) =>
        j.status === 'queued' ? (
          <button type="button" className="btn-dash" onClick={() => setDoomed(j)}>
            <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
            {t(lang, 'admin.ops.cancel')}
          </button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-8" data-testid="admin-operations">
      <section aria-labelledby="ops-jobs" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="ops-jobs" className="text-lg font-bold text-foreground">{t(lang, 'admin.ops.jobs')}</h2>
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label={t(lang, 'admin.ops.colStatus')} className={FIELD}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s ? t(lang, `admin.ops.status.${s}` as MessageKey) : t(lang, 'admin.ops.status.all')}
                {s && jobs.data ? ` (${jobs.data.counts[s] ?? 0})` : ''}
              </option>
            ))}
          </select>
        </div>
        {jobs.error && <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.ops.loadFailed', { error: jobs.error })}</p>}
        {!jobs.data && !jobs.error && (
          <div className="flex items-center gap-2 text-sm text-foreground-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'admin.ops.loading')}
          </div>
        )}
        {jobs.data && (
          <>
            <AdminTable columns={columns} rows={jobs.data.jobs} rowKey={(j) => j.id} empty={t(lang, 'admin.ops.jobsEmpty')} label={t(lang, 'admin.ops.jobs')} />
            <p className="text-xs text-foreground-muted">{t(lang, 'admin.ops.retention', { days: jobs.data.retention_days })}</p>
          </>
        )}
      </section>

      <section aria-labelledby="ops-config" className="space-y-3">
        <h2 id="ops-config" className="text-lg font-bold text-foreground">{t(lang, 'admin.ops.config')}</h2>
        <p className="text-xs text-foreground-muted">{t(lang, 'admin.ops.configNote')}</p>
        {config.error && <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.ops.loadFailed', { error: config.error })}</p>}
        {config.data && (
          <div className="grid gap-4 lg:grid-cols-2">
            {config.data.groups.map((group) => (
              <div key={group.group} className="space-y-1.5">
                <h3 className="text-sm font-bold text-foreground">{t(lang, `admin.ops.group.${group.group}` as MessageKey)}</h3>
                <dl className="divide-y divide-border rounded-lg border border-border">
                  {group.items.map((item) => (
                    <div key={item.key} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-3 py-2 text-xs">
                      <dt className="font-mono text-foreground-muted">{item.key}</dt>
                      <dd className="break-all text-right font-medium tabular-nums text-foreground">{configValue(group.group, item, lang)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        )}
      </section>

      <ConfirmDialog
        open={doomed !== null}
        title={t(lang, 'admin.ops.cancelTitle', { id: doomed?.id ?? '' })}
        body={t(lang, 'admin.ops.cancelBody')}
        confirmLabel={t(lang, 'admin.ops.cancel')}
        danger
        busy={cancelling}
        onConfirm={() => void cancel()}
        onCancel={() => setDoomed(null)}
      />
    </div>
  );
};
