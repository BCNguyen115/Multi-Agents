'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import { AdminTable, type Column } from './AdminTable';
import { getAudit, getOrg, type AuditFilter, type AuditRow } from '../../lib/adminApi';
import { auditParams, formatTime } from '../../lib/adminConsole';
import { t, useLang, type MessageKey } from '../../lib/i18n';
import { useAdminData } from '../../lib/useAdminData';

const PAGE = 50;
const GROUPS = ['admin', 'hitl', 'kb', 'dash', 'auth'] as const;
const OUTCOMES = ['ok', 'pending', 'decided', 'denied', 'failed']; // suggestions only: the field takes any text
const FIELD =
  'w-full rounded-md border border-border-input bg-surface px-2 py-1.5 text-base sm:text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary';

/** The append-only audit trail: filter by who, what, where and when, read the detail of a row, page back in time, take the filtered rows as CSV. */
export const AdminAudit: React.FC = () => {
  const [lang] = useLang();
  const [draft, setDraft] = useState<AuditFilter>({});
  const [applied, setApplied] = useState<AuditFilter>({});
  const [more, setMore] = useState<AuditRow[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [paging, setPaging] = useState(false);
  const [pagingError, setPagingError] = useState<string | null>(null);

  const fetcher = useCallback(() => getAudit(auditParams(applied, { limit: PAGE })), [applied]);
  const { data, error, busy } = useAdminData(fetcher);
  const orgFetcher = useCallback(() => getOrg(), []);
  const org = useAdminData(orgFetcher); // only to suggest tenant ids; the filter works without it

  useEffect(() => {
    setMore([]);
    setCursor(data?.next_before ?? null); // a new answer to the filter starts the paging over
  }, [data]);

  const loadMore = async () => {
    if (cursor === null) return;
    setPaging(true);
    setPagingError(null);
    try {
      const page = await getAudit(auditParams(applied, { limit: PAGE, before: cursor }));
      setMore((rows) => [...rows, ...page.rows]);
      setCursor(page.next_before);
    } catch (e: unknown) {
      setPagingError(e instanceof Error ? e.message : String(e));
    } finally {
      setPaging(false);
    }
  };

  const put = (key: keyof AuditFilter) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setDraft((d) => ({ ...d, [key]: event.target.value }));
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setApplied({ ...draft });
  };
  const clear = () => {
    setDraft({});
    setApplied({});
  };

  const rows = [...(data?.rows ?? []), ...more];
  const columns: Column<AuditRow>[] = [
    { key: 'when', label: t(lang, 'admin.audit.colWhen'), cell: (r) => formatTime(r.at, lang), className: 'whitespace-nowrap tabular-nums text-foreground-muted' },
    { key: 'actor', label: t(lang, 'admin.audit.colActor'), cell: (r) => r.actor, className: 'font-medium text-foreground' },
    { key: 'action', label: t(lang, 'admin.audit.colAction'), cell: (r) => <span className="font-mono">{r.action}</span> },
    { key: 'target', label: t(lang, 'admin.audit.colTarget'), cell: (r) => <span className="break-all font-mono text-foreground-secondary">{r.target || '–'}</span> },
    { key: 'tenant', label: t(lang, 'admin.audit.colTenant'), cell: (r) => r.tenant_id || '–', className: 'text-foreground-secondary' },
    { key: 'outcome', label: t(lang, 'admin.audit.colOutcome'), cell: (r) => <span className={r.outcome === 'denied' || r.outcome === 'failed' ? 'font-semibold text-accent-error' : ''}>{r.outcome}</span> },
    {
      key: 'detail',
      label: t(lang, 'admin.audit.colDetail'),
      cell: (r) =>
        Object.keys(r.detail ?? {}).length === 0 ? (
          '–'
        ) : (
          <details>
            <summary className="cursor-pointer text-accent-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary">{t(lang, 'admin.audit.showDetail')}</summary>
            <pre className="mt-1 max-w-xs overflow-x-auto whitespace-pre-wrap break-words font-mono text-[11px] text-foreground-secondary">{JSON.stringify(r.detail, null, 2)}</pre>
          </details>
        ),
    },
  ];

  return (
    <section aria-label={t(lang, 'admin.audit.title')} className="space-y-4" data-testid="admin-audit">
      <form onSubmit={submit} className="space-y-3 rounded-lg border border-border p-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="space-y-1 text-xs text-foreground-secondary">
            <span className="font-semibold">{t(lang, 'admin.audit.actor')}</span>
            <input value={draft.actor ?? ''} onChange={put('actor')} maxLength={64} className={FIELD} />
          </label>
          <label className="space-y-1 text-xs text-foreground-secondary">
            <span className="font-semibold">{t(lang, 'admin.audit.action')}</span>
            <select value={draft.action ?? ''} onChange={put('action')} className={FIELD}>
              <option value="">{t(lang, 'admin.audit.actionAll')}</option>
              {GROUPS.map((g) => (
                <option key={g} value={`${g}.`}>{`${t(lang, `admin.audit.group.${g}` as MessageKey)} (${g}.)`}</option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-xs text-foreground-secondary">
            <span className="font-semibold">{t(lang, 'admin.audit.tenant')}</span>
            <input list="audit-tenants" value={draft.tenant ?? ''} onChange={put('tenant')} maxLength={64} className={FIELD} />
            <datalist id="audit-tenants">{(org.data ?? []).map((o) => <option key={o.id} value={o.id} />)}</datalist>
          </label>
          <label className="space-y-1 text-xs text-foreground-secondary">
            <span className="font-semibold">{t(lang, 'admin.audit.outcome')}</span>
            <input list="audit-outcomes" value={draft.outcome ?? ''} onChange={put('outcome')} maxLength={40} className={FIELD} />
            <datalist id="audit-outcomes">{OUTCOMES.map((o) => <option key={o} value={o} />)}</datalist>
          </label>
          <label className="space-y-1 text-xs text-foreground-secondary sm:col-span-2">
            <span className="font-semibold">{t(lang, 'admin.audit.search')}</span>
            <input value={draft.q ?? ''} onChange={put('q')} maxLength={100} className={FIELD} />
          </label>
          <label className="space-y-1 text-xs text-foreground-secondary">
            <span className="font-semibold">{t(lang, 'admin.audit.since')}</span>
            <input type="date" value={draft.since ?? ''} onChange={put('since')} className={FIELD} />
          </label>
          <label className="space-y-1 text-xs text-foreground-secondary">
            <span className="font-semibold">{t(lang, 'admin.audit.until')}</span>
            <input type="date" value={draft.until ?? ''} onChange={put('until')} className={FIELD} />
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
            {t(lang, 'admin.audit.apply')}
          </button>
          <button type="button" className="btn-dash" onClick={clear}>{t(lang, 'admin.audit.reset')}</button>
          <a className="btn-dash" href={`/api/admin/audit/export${auditParams(applied)}`} download>
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            {t(lang, 'admin.audit.export')}
          </a>
          {data && <span className="text-xs text-foreground-muted">{t(lang, 'admin.audit.count', { count: rows.length })}</span>}
        </div>
      </form>

      {error && <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.audit.loadFailed', { error })}</p>}
      {!data && !error && (
        <div className="flex items-center gap-2 text-sm text-foreground-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'admin.audit.loading')}
        </div>
      )}
      {data && <AdminTable columns={columns} rows={rows} rowKey={(r) => String(r.id)} empty={t(lang, 'admin.audit.empty')} label={t(lang, 'admin.audit.title')} />}
      {pagingError && <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.audit.loadFailed', { error: pagingError })}</p>}
      {cursor !== null && (
        <button type="button" className="btn-dash" onClick={() => void loadMore()} disabled={paging}>
          {paging && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          {t(lang, 'admin.audit.more')}
        </button>
      )}
    </section>
  );
};
