'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Check, Loader2, Minus, RefreshCw } from 'lucide-react';
import { AdminFacts } from './AdminFacts';
import { AdminTable } from './AdminTable';
import { AdminPageHeader } from './AdminPageHeader';
import { getAlerts, getBackup, getHealth, type AdminHealthData, type AlertsReport, type BackupReport, type ServiceStatus } from '../../lib/adminApi';
import { formatAge, formatBytes, formatTime, serviceState } from '../../lib/adminConsole';
import { t, useLang, type MessageKey } from '../../lib/i18n';

const REFRESH_MS = 15_000;
const BACKUP_STALE_HOURS = 36;
const number = (value: number) => value.toLocaleString('en-US');

function ServiceTile({ name, result }: { name: string; result: ServiceStatus }) {
  const [lang] = useLang();
  const state = serviceState(result.status);
  const Icon = state === 'ok' ? Check : state === 'off' ? Minus : AlertTriangle;
  const tone = state === 'fail' ? 'text-accent-error' : state === 'off' ? 'text-foreground-muted' : 'text-foreground';
  return (
    <li className={`rounded-lg border p-3 ${state === 'fail' ? 'border-accent-error/40' : 'border-border'}`}>
      <p className="text-xs font-semibold text-foreground-muted">{t(lang, `admin.health.service.${name}` as MessageKey)}</p>
      <p className={`mt-1 flex items-center gap-1.5 text-sm font-semibold ${tone}`}>
        <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
        {state === 'fail' ? t(lang, 'admin.health.state.fail', { reason: result.status }) : t(lang, `admin.health.state.${state}` as MessageKey)}
      </p>
      {state !== 'off' && <p className="mt-0.5 text-xs tabular-nums text-foreground-muted">{result.ms} ms</p>}
    </li>
  );
}

/** Is everything up, which database revision runs, how this instance's requests fare, what the job queue holds. Refreshes while the tab is visible. */
export const AdminMonitoring: React.FC = () => {
  const [lang] = useLang();
  const [data, setData] = useState<AdminHealthData | null>(null);
  const [alerts, setAlerts] = useState<AlertsReport | null>(null);
  const [backup, setBackup] = useState<BackupReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      // alerts and backups are extras: when one cannot be read the rest of the page still shows
      const [health, firing, backups] = await Promise.all([getHealth(), getAlerts().catch(() => null), getBackup().catch(() => null)]);
      setData(health);
      setAlerts(firing);
      setBackup(backups);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const refresh = () => {
      if (document.visibilityState === 'visible') void load(); // a hidden tab asks nothing; coming back asks at once
    };
    const timer = window.setInterval(refresh, REFRESH_MS);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [load]);

  const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString(lang === 'vi' ? 'vi-VN' : 'en-GB') : '–');
  const header = <AdminPageHeader title={t(lang, 'admin.health.title')} description={t(lang, 'admin.health.subtitle')} />;

  if (!data) {
    return (
      <div className="space-y-6">
        {header}
        {error ? (
          <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.health.loadFailed', { error })}</p>
        ) : (
          <div className="flex items-center gap-2 text-sm text-foreground-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'admin.health.loading')}
          </div>
        )}
      </div>
    );
  }

  const { instance, http, queue } = data;
  const down = data.status === 'down';
  return (
    <div className="space-y-6" data-testid="admin-monitoring">
      {header}

      <div className="flex flex-wrap items-center gap-3 text-xs text-foreground-muted">
        <button type="button" className="btn-dash" onClick={() => void load()} disabled={busy}>
          <RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} aria-hidden="true" /> {t(lang, 'admin.health.refresh')}
        </button>
        <span>{t(lang, 'admin.health.updated', { time: when(data.checked_at) })}</span>
        <span>{t(lang, 'admin.health.auto')}</span>
        {error && <span role="alert" className="text-accent-error">{t(lang, 'admin.health.loadFailed', { error })}</span>}
      </div>

      <div
        role={down ? 'alert' : 'status'}
        className={`flex items-center gap-2 rounded-lg border px-4 py-3 text-sm font-semibold ${down ? 'border-accent-error/40 bg-accent-error/10 text-accent-error' : 'border-border text-foreground'}`}
      >
        {data.status === 'ok' ? <Check className="h-4 w-4 shrink-0" aria-hidden="true" /> : <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />}
        {t(lang, `admin.health.status.${data.status}` as MessageKey)}
      </div>

      <section aria-labelledby="health-services" className="space-y-2">
        <h2 id="health-services" className="text-lg font-bold text-foreground">{t(lang, 'admin.health.services')}</h2>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {Object.entries(data.services).map(([name, result]) => <ServiceTile key={name} name={name} result={result} />)}
        </ul>
      </section>

      <section aria-labelledby="health-alerts" className="space-y-2">
        <h2 id="health-alerts" className="text-lg font-bold text-foreground">{t(lang, 'admin.health.alerts')}</h2>
        {alerts && !alerts.configured && <p className="text-sm text-foreground-secondary">{t(lang, 'admin.health.alertsOff')}</p>}
        {alerts?.configured && alerts.error && <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.health.alertsError', { error: alerts.error })}</p>}
        {alerts?.configured && !alerts.error && alerts.alerts.length === 0 && <p className="text-sm text-foreground-secondary">{t(lang, 'admin.health.alertsNone')}</p>}
        {alerts?.configured && alerts.alerts.length > 0 && (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {alerts.alerts.map((a) => (
              <li key={`${a.name}-${a.since}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-4 py-3 text-sm">
                <span className={`font-semibold ${a.severity === 'critical' ? 'text-accent-error' : 'text-foreground'}`}>{a.name}</span>
                <span className="text-foreground-secondary">{a.summary}</span>
                {a.since && <span className="text-xs text-foreground-muted">{t(lang, 'admin.health.alertSince', { time: formatTime(a.since, lang) })}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="health-backup" className="space-y-2">
        <h2 id="health-backup" className="text-lg font-bold text-foreground">{t(lang, 'admin.health.backup')}</h2>
        {backup && !backup.configured && <p className="text-sm text-foreground-secondary">{t(lang, 'admin.health.backupOff')}</p>}
        {backup?.configured && backup.error && <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.health.backupError', { error: backup.error })}</p>}
        {backup?.configured && !backup.error && !backup.latest && <p className="text-sm text-accent-error">{t(lang, 'admin.health.backupNone')}</p>}
        {backup?.configured && backup.latest && (
          <>
            <AdminFacts
              rows={[
                [t(lang, 'admin.health.backupLatest'), <span key="n" className="font-mono">{backup.latest.name}</span>],
                [t(lang, 'admin.health.backupAge'), formatAge(backup.latest.age_seconds)],
                [t(lang, 'admin.health.backupSize'), formatBytes(backup.latest.size)],
                [t(lang, 'admin.health.backupCount'), number(backup.count ?? 0)],
              ]}
            />
            {backup.latest.age_seconds > BACKUP_STALE_HOURS * 3600 && (
              <p role="alert" className="text-sm font-semibold text-accent-error">{t(lang, 'admin.health.backupStale', { hours: BACKUP_STALE_HOURS })}</p>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="health-instance" className="space-y-2">
        <h2 id="health-instance" className="text-lg font-bold text-foreground">{t(lang, 'admin.health.instance')}</h2>
        <AdminFacts
          rows={[
            [t(lang, 'admin.health.hostname'), <span key="h" className="font-mono">{instance.hostname}</span>],
            [t(lang, 'admin.health.uptime'), formatAge(instance.uptime_seconds)],
            [
              t(lang, 'admin.health.dbRevision'),
              instance.db_current ? (
                t(lang, 'admin.health.dbOk', { current: instance.db_revision ?? '–' })
              ) : (
                <span key="r" className="text-accent-error">{t(lang, 'admin.health.dbBehind', { current: instance.db_revision ?? '–', head: instance.db_head })}</span>
              ),
            ],
          ]}
        />
      </section>

      <section aria-labelledby="health-http" className="space-y-2">
        <h2 id="health-http" className="text-lg font-bold text-foreground">{t(lang, 'admin.health.http')}</h2>
        <AdminFacts
          rows={[
            [t(lang, 'admin.health.total'), number(http.total)],
            [t(lang, 'admin.health.errors5xx'), <span key="5" className={http.by_class['5xx'] > 0 ? 'text-accent-error' : ''}>{number(http.by_class['5xx'] ?? 0)}</span>],
            [t(lang, 'admin.health.errors4xx'), number(http.by_class['4xx'] ?? 0)],
            [t(lang, 'admin.health.rateLimited'), number(http.rate_limited)],
            [t(lang, 'admin.health.errorRate'), `${(http.error_rate * 100).toFixed(1)}%`],
          ]}
        />
        <h3 className="pt-2 text-sm font-bold text-foreground">{t(lang, 'admin.health.routes')}</h3>
        {http.routes.length === 0 ? (
          <p className="text-sm text-foreground-secondary">{t(lang, 'admin.health.routesEmpty')}</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-left text-xs">
              <thead className="bg-surface-raised text-foreground-muted">
                <tr>
                  <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'admin.health.colRoute')}</th>
                  <th scope="col" className="px-3 py-2 text-right font-semibold">{t(lang, 'admin.health.colCount')}</th>
                  <th scope="col" className="px-3 py-2 text-right font-semibold">{t(lang, 'admin.health.colErrors')}</th>
                  <th scope="col" className="px-3 py-2 text-right font-semibold">{t(lang, 'admin.health.colAvg')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {http.routes.map((r) => (
                  <tr key={`${r.method} ${r.route}`} className="hover:bg-surface-raised/50">
                    <td className="px-3 py-2"><span className="font-mono text-foreground-muted">{r.method}</span> <span className="font-mono text-foreground">{r.route}</span></td>
                    <td className="px-3 py-2 text-right tabular-nums">{number(r.count)}</td>
                    <td className={`px-3 py-2 text-right tabular-nums ${r.errors > 0 ? 'text-accent-error' : ''}`}>{number(r.errors)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{r.avg_ms} ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="health-pev" className="space-y-2">
        <h2 id="health-pev" className="text-lg font-bold text-foreground">{t(lang, 'admin.health.pev')}</h2>
        <p className="max-w-3xl text-xs text-foreground-muted">{t(lang, 'admin.health.pevHint')}</p>
        <AdminTable
          label={t(lang, 'admin.health.pev')}
          empty={t(lang, 'admin.health.pevEmpty')}
          rows={http.pev ?? []}
          rowKey={(r) => r.agent}
          columns={[
            { key: 'agent', label: t(lang, 'admin.health.colAgent'), cell: (r) => <span className="font-mono">{r.agent}</span> },
            { key: 'runs', label: t(lang, 'admin.health.colRuns'), cell: (r) => number(r.runs), numeric: true },
            { key: 'passed', label: t(lang, 'admin.health.colPassed'), cell: (r) => number(r.verified), numeric: true },
            { key: 'notPassed', label: t(lang, 'admin.health.colNotPassed'), cell: (r) => <span className={r.unverified > 0 ? 'text-accent-error' : ''}>{number(r.unverified)}</span>, numeric: true },
            { key: 'retries', label: t(lang, 'admin.health.colRetries'), cell: (r) => number(r.retries), numeric: true },
            { key: 'rate', label: t(lang, 'admin.health.colNotPassedRate'), cell: (r) => `${r.runs ? ((r.unverified / r.runs) * 100).toFixed(1) : '0.0'}%`, numeric: true },
          ]}
        />
      </section>

      <section aria-labelledby="health-queue" className="space-y-2">
        <h2 id="health-queue" className="text-lg font-bold text-foreground">{t(lang, 'admin.health.queue')}</h2>
        <AdminFacts
          rows={[
            [t(lang, 'admin.health.queued'), number(queue.queued)],
            [t(lang, 'admin.health.running'), number(queue.running)],
            [t(lang, 'admin.health.failed'), <span key="f" className={queue.failed_24h > 0 ? 'text-accent-error' : ''}>{number(queue.failed_24h)}</span>],
            [t(lang, 'admin.health.oldest'), queue.queued > 0 ? formatAge(queue.oldest_queued_seconds) : '–'],
          ]}
        />
        <h3 className="pt-2 text-sm font-bold text-foreground">{t(lang, 'admin.health.failures')}</h3>
        {queue.recent_failures.length === 0 ? (
          <p className="text-sm text-foreground-secondary">{t(lang, 'admin.health.noFailures')}</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-left text-xs">
              <thead className="bg-surface-raised text-foreground-muted">
                <tr>
                  <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'admin.health.colKind')}</th>
                  <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'admin.health.colUser')}</th>
                  <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'admin.health.colReason')}</th>
                  <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'admin.health.colWhen')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {queue.recent_failures.map((job) => (
                  <tr key={job.id} className="align-top hover:bg-surface-raised/50">
                    <td className="px-3 py-2 font-mono">{job.kind}</td>
                    <td className="px-3 py-2">{job.user_id || '–'}</td>
                    <td className="px-3 py-2 break-words text-foreground-secondary">{job.error}</td>
                    <td className="whitespace-nowrap px-3 py-2 tabular-nums text-foreground-muted">{when(job.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
};
