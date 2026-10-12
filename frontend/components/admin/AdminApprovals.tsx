'use client';

import React, { useCallback } from 'react';
import Link from 'next/link';
import { Loader2, ShieldCheck } from 'lucide-react';
import { AdminTable, type Column } from './AdminTable';
import { useAuth } from '../../context/AuthContext';
import { getApprovals, getAudit, type AuditRow, type PendingApproval } from '../../lib/adminApi';
import { auditParams, formatAge, formatTime } from '../../lib/adminConsole';
import { t, useLang } from '../../lib/i18n';
import { useAdminData } from '../../lib/useAdminData';

const REFRESH_MS = 15_000;

/** What waits for an approver system-wide, and the decisions already taken (the audit trail's `hitl.` rows). Deciding stays with the approvers. */
export const AdminApprovals: React.FC = () => {
  const [lang] = useLang();
  const { me, openApprovals } = useAuth();
  const pendingFetcher = useCallback(() => getApprovals(), []);
  const historyFetcher = useCallback(() => getAudit(auditParams({ action: 'hitl.' }, { limit: 20 })), []);
  const pending = useAdminData(pendingFetcher, REFRESH_MS);
  const history = useAdminData(historyFetcher, REFRESH_MS);

  const pendingColumns: Column<PendingApproval>[] = [
    {
      key: 'action',
      label: t(lang, 'admin.approvals.colAction'),
      cell: (a) => <span className="font-mono">{[a.agent, a.action_type].filter(Boolean).join(' · ') || '–'}</span>,
    },
    { key: 'description', label: t(lang, 'admin.approvals.colDescription'), cell: (a) => a.description || '–', className: 'min-w-[12rem] text-foreground' },
    {
      key: 'risk',
      label: t(lang, 'admin.approvals.colRisk'),
      cell: (a) => <span className={a.risk_level === 'high' ? 'font-semibold text-accent-error' : ''}>{a.risk_level || '–'}</span>,
    },
    { key: 'by', label: t(lang, 'admin.approvals.colBy'), cell: (a) => a.requested_by || '–', className: 'font-medium text-foreground' },
    { key: 'tenant', label: t(lang, 'admin.approvals.colTenant'), cell: (a) => a.tenant_id || '–', className: 'text-foreground-secondary' },
    { key: 'expires', label: t(lang, 'admin.approvals.colExpires'), cell: (a) => formatAge(a.expires_in), numeric: true },
  ];
  const historyColumns: Column<AuditRow>[] = [
    { key: 'when', label: t(lang, 'admin.audit.colWhen'), cell: (r) => formatTime(r.at, lang), className: 'whitespace-nowrap tabular-nums text-foreground-muted' },
    { key: 'action', label: t(lang, 'admin.audit.colAction'), cell: (r) => <span className="font-mono">{r.action}</span> },
    { key: 'actor', label: t(lang, 'admin.audit.colActor'), cell: (r) => r.actor, className: 'font-medium text-foreground' },
    { key: 'target', label: t(lang, 'admin.audit.colTarget'), cell: (r) => <span className="font-mono text-foreground-secondary">{r.target || '–'}</span> },
    { key: 'outcome', label: t(lang, 'admin.audit.colOutcome'), cell: (r) => r.outcome },
  ];

  const loading = !pending.data && !pending.error;
  return (
    <div className="space-y-6" data-testid="admin-approvals">
      {pending.error && <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.approvals.loadFailed', { error: pending.error })}</p>}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-foreground-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'admin.approvals.loading')}
        </div>
      )}

      {pending.data && (
        <section aria-labelledby="approvals-pending" className="space-y-2">
          <h2 id="approvals-pending" className="text-lg font-bold text-foreground">{t(lang, 'admin.approvals.pending')}</h2>
          <p className="text-xs text-foreground-muted">{t(lang, pending.data.two_person ? 'admin.approvals.twoPersonOn' : 'admin.approvals.twoPersonOff')}</p>
          {me?.can_approve && me.two_person_approval && (
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" className="btn-dash" onClick={openApprovals}>
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                {t(lang, 'admin.approvals.openInbox')}
              </button>
              <span className="text-xs text-foreground-muted">{t(lang, 'admin.approvals.openInboxHint')}</span>
            </div>
          )}
          {!pending.data.available && <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.approvals.unavailable')}</p>}
          <AdminTable columns={pendingColumns} rows={pending.data.items} rowKey={(a) => a.action_id} empty={t(lang, 'admin.approvals.empty')} label={t(lang, 'admin.approvals.pending')} />
        </section>
      )}

      <section aria-labelledby="approvals-history" className="space-y-2">
        <h2 id="approvals-history" className="text-lg font-bold text-foreground">{t(lang, 'admin.approvals.history')}</h2>
        {history.data && <AdminTable columns={historyColumns} rows={history.data.rows} rowKey={(r) => String(r.id)} empty={t(lang, 'admin.approvals.historyEmpty')} label={t(lang, 'admin.approvals.history')} />}
        <Link href="/admin/audit" className="inline-block text-sm font-medium text-accent-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary">
          {t(lang, 'admin.approvals.seeAll')}
        </Link>
      </section>
    </div>
  );
};
