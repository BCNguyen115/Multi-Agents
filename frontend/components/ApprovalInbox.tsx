'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Database, Globe, Loader2, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch } from '../lib/apiFetch';
import { isUnauthorized } from '../lib/authClient';
import { t, useLang } from '../lib/i18n';
import { toast } from '../lib/toast';
import { useDialogA11y } from '../lib/useDialogA11y';

interface PendingItem {
  action_id: string;
  agent: string | null;
  action_type: string | null;
  description: string | null;
  risk_level: string | null;
  request: { sql?: string; url?: string; method?: string; payload?: unknown } | null;
  requested_by: string;
  expires_in: number;
}

const REFRESH_MS = 10_000;
const BUTTON =
  'inline-flex min-h-10 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold cursor-pointer transition-colors ' +
  'disabled:opacity-60 disabled:cursor-default focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40';

/**
 * Two-person approval: the sensitive actions OTHER people asked for, in this approver's tenant. Deciding here runs the action in the
 * requester's scope and sends the result to the requester; the approver sees the request, never the data it returns.
 */
export function ApprovalInbox() {
  const [lang] = useLang();
  const { approvalsOpen, closeApprovals } = useAuth();
  const [items, setItems] = useState<PendingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useDialogA11y(approvalsOpen, dialogRef, closeApprovals, busy === null);

  const load = useCallback(async () => {
    try {
      const response = await apiFetch('/api/approvals', { cache: 'no-store' });
      if (isUnauthorized(response)) return;
      if (!response.ok) throw new Error(String(response.status));
      setItems(await response.json());
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!approvalsOpen) return undefined;
    setLoading(true);
    setConfirming(null);
    void load();
    const timer = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [approvalsOpen, load]);

  if (!approvalsOpen || typeof document === 'undefined') return null;

  const decide = async (item: PendingItem, decision: 'approve' | 'reject') => {
    if (busy) return;
    if (decision === 'approve' && item.risk_level === 'critical' && confirming !== item.action_id) {
      setConfirming(item.action_id); // a critical action needs a second click, like in the requester's own card
      return;
    }
    setBusy(item.action_id);
    try {
      const response = await apiFetch('/api/chat/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: 'approvals-inbox', action_id: item.action_id, decision }),
      });
      const data = await response.json().catch(() => ({}));
      if (isUnauthorized(response)) return;
      if (!response.ok) throw new Error(data.detail || data.message || String(response.status));
      setItems((prev) => prev.filter((i) => i.action_id !== item.action_id));
      toast.success(t(lang, 'approval.inbox.done'), { title: 'HITL' });
    } catch (error: any) {
      toast.error(t(lang, 'approval.errorToast', { error: error?.message || t(lang, 'nav.unknownError') }), { title: t(lang, 'approval.errorTitle') });
      void load();
    } finally {
      setBusy(null);
      setConfirming(null);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-background/60 backdrop-blur-sm" data-testid="approval-inbox">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="approvals-title"
        className="relative w-full max-w-2xl max-h-[calc(100vh-2rem)] overflow-y-auto rounded-2xl border border-border-strong bg-surface p-6 shadow-lg animate-fade-in-scale"
      >
        <button
          type="button"
          onClick={closeApprovals}
          disabled={busy !== null}
          aria-label={t(lang, 'auth.close')}
          className="absolute right-3 top-3 w-9 h-9 rounded-full flex items-center justify-center text-foreground-secondary hover:text-foreground hover:bg-surface-raised transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
        >
          <X className="w-[18px] h-[18px]" aria-hidden="true" />
        </button>
        <h2 id="approvals-title" className="pr-10 text-xl font-semibold text-foreground">{t(lang, 'approval.inbox.title')}</h2>
        <p className="mt-1 text-sm text-foreground-secondary">{t(lang, 'approval.inbox.hint')}</p>

        <div className="mt-5 space-y-3" aria-live="polite">
          {loading && (
            <p className="flex items-center gap-2 text-sm text-foreground-muted">
              <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
              {t(lang, 'nav.loading')}
            </p>
          )}
          {failed && <p role="alert" className="text-sm text-accent-error">{t(lang, 'approval.inbox.failed')}</p>}
          {!loading && !failed && items.length === 0 && <p className="text-sm text-foreground-muted">{t(lang, 'approval.inbox.empty')}</p>}

          {items.map((item) => {
            const request = item.request ?? {};
            const critical = item.risk_level === 'critical';
            const working = busy === item.action_id;
            return (
              <article key={item.action_id} className="rounded-xl border border-border-strong bg-background p-4" data-testid="approval-item">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span className={`rounded-full border px-2 py-0.5 font-semibold uppercase ${critical ? 'border-accent-error/30 bg-accent-error/15 text-accent-error' : 'border-border bg-surface-raised text-foreground-secondary'}`}>
                    {t(lang, 'approval.risk', { level: item.risk_level ?? '' })}
                  </span>
                  <span className="text-foreground-muted">
                    {t(lang, 'approval.inbox.requestedBy', { user: item.requested_by })} · {t(lang, 'approval.inbox.expires', { minutes: Math.max(1, Math.ceil(item.expires_in / 60)) })}
                  </span>
                </div>
                <p className="mt-2 flex items-center gap-2 text-sm font-medium text-foreground">
                  {item.agent === 'db_agent' ? <Database className="w-4 h-4 shrink-0 text-foreground-secondary" aria-hidden="true" /> : <Globe className="w-4 h-4 shrink-0 text-foreground-secondary" aria-hidden="true" />}
                  {request.sql ? t(lang, 'approval.willRunSql') : t(lang, 'approval.willCall', { method: request.method || 'POST', url: request.url || '' })}
                </p>
                {item.description && <p className="mt-1 text-sm text-foreground-secondary break-words">{item.description}</p>}
                <pre className="mt-2 max-h-48 overflow-auto rounded-lg border border-border bg-surface p-3 font-mono text-xs text-foreground whitespace-pre-wrap break-all">
                  {request.sql ?? `${request.method || ''} ${request.url || ''}\n${request.payload ? JSON.stringify(request.payload, null, 2) : ''}`}
                </pre>
                {critical && confirming === item.action_id && <p className="mt-2 text-xs text-foreground-secondary">{t(lang, 'approval.criticalHint')}</p>}
                <div className="mt-3 flex flex-wrap justify-end gap-2">
                  <button type="button" className={`${BUTTON} border border-border-strong text-foreground hover:bg-surface-raised`} disabled={busy !== null} onClick={() => decide(item, 'reject')}>
                    {t(lang, 'approval.reject')}
                  </button>
                  <button type="button" className={`${BUTTON} bg-accent-primary text-white hover:bg-accent-primary-hover`} disabled={busy !== null} onClick={() => decide(item, 'approve')}>
                    {working && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
                    {confirming === item.action_id ? t(lang, 'approval.confirmApprove') : t(lang, 'approval.approve')}
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </div>,
    document.body
  );
}
