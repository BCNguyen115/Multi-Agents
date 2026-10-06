'use client';

import React, { useEffect, useState } from 'react';
import { HumanApprovalRequest } from '@/lib/types';
import { isUnauthorized } from '@/lib/authClient';
import {
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Check,
  X,
  Loader2,
  Database,
  Globe,
  Copy,
} from 'lucide-react';
import { toast } from '@/lib/toast';
import { apiFetch } from '@/lib/apiFetch';
import { useAuth } from '@/context/AuthContext';
import { describeOutcome, type ApprovalOutcome } from '@/lib/approvalResult';
import { getLang, t, useLang } from '@/lib/i18n';

interface ApprovalCardProps {
  approvalRequest: HumanApprovalRequest;
  sessionId: string;
  onDecisionSubmitted?: (
    actionId: string,
    decision: 'approve' | 'reject',
    responseText?: string
  ) => void;
}

export const ApprovalCard: React.FC<ApprovalCardProps> = ({
  approvalRequest,
  sessionId,
  onDecisionSubmitted,
}) => {
  const [lang] = useLang();
  const { me } = useAuth();
  const waitingForOther = Boolean(me?.two_person_approval); // somebody ELSE decides: this card only waits for the outcome
  const [expired, setExpired] = useState(false);
  const [decision, setDecision] = useState<'approved' | 'rejected' | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [showReasonInput, setShowReasonInput] = useState(false);
  const [confirmingApprove, setConfirmingApprove] = useState(false);
  const [copied, setCopied] = useState(false);
  const [executionResult, setExecutionResult] = useState<string | null>(null);

  const { action_id, agent, action_type, description, payload, risk_level } =
    approvalRequest;

  const isCritical = risk_level === 'critical';

  // Risk is told by the badge text; only critical gets the alert color (state colors keep their one meaning).
  const riskBadgeClass = isCritical
    ? 'bg-accent-error/15 text-accent-error border-accent-error/30'
    : 'bg-surface-raised text-foreground-secondary border-border';

  // Two-person approval: poll for the outcome until the other person has decided (or the request expired)
  useEffect(() => {
    if (!waitingForOther || decision !== null || expired) return undefined;
    let stopped = false;
    const poll = async () => {
      try {
        const response = await apiFetch(`/api/chat/approve/${encodeURIComponent(action_id)}/result`, { cache: 'no-store' });
        if (stopped) return;
        if (response.status === 404) {
          setExpired(true);
          return;
        }
        if (!response.ok) return;
        const outcome = describeOutcome((await response.json()) as ApprovalOutcome);
        if (!outcome || stopped) return;
        setDecision(outcome.decision);
        setExecutionResult(outcome.text);
        onDecisionSubmitted?.(action_id, outcome.decision === 'approved' ? 'approve' : 'reject', outcome.text);
      } catch {
        /* offline for a moment: the next tick tries again */
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 3000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [waitingForOther, decision, expired, action_id, onDecisionSubmitted]);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDecision = async (userDecision: 'approve' | 'reject') => {
    if (userDecision === 'reject' && !showReasonInput) {
      setConfirmingApprove(false);
      setShowReasonInput(true);
      return;
    }
    if (userDecision === 'approve' && isCritical && !confirmingApprove) {
      setShowReasonInput(false);
      setConfirmingApprove(true);
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await apiFetch('/api/chat/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          action_id,
          decision: userDecision,
          feedback: rejectReason.trim() || undefined,
        }),
      });

      const data = await res.json().catch(() => ({}));
      if (isUnauthorized(res)) throw new Error(t(getLang(), 'session.expired'));
      if (!res.ok) {
        throw new Error(data.detail || data.message || t(getLang(), 'approval.sendFailed'));
      }

      setDecision(userDecision === 'approve' ? 'approved' : 'rejected');
      const responseText = data.response || data.message || '';
      setExecutionResult(responseText);
      if (userDecision === 'approve') {
        toast.success(t(getLang(), 'approval.approvedToast'), { title: 'HITL' });
      } else {
        toast.warning(t(getLang(), 'approval.rejectedToast'), { title: 'HITL' });
      }
      if (onDecisionSubmitted) {
        onDecisionSubmitted(action_id, userDecision, responseText);
      }
    } catch (err: any) {
      setConfirmingApprove(false);
      toast.error(t(getLang(), 'approval.errorToast', { error: err?.message || t(getLang(), 'nav.unknownError') }), { title: t(getLang(), 'approval.errorTitle') });
    } finally {
      setIsSubmitting(false);
    }
  };

  const focusRing = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40';

  return (
    <div
      role="group"
      aria-label={t(lang, 'approval.pendingTitle')}
      className={`my-3 p-4 rounded-xl border bg-surface transition-colors duration-200 ${
        decision === 'approved'
          ? 'border-accent-primary/40'
          : decision === 'rejected'
          ? 'border-border-strong'
          : isCritical
          ? 'border-accent-error/50'
          : 'border-border-strong'
      }`}
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-border">
        <div className="flex items-center gap-2 min-w-0">
          {decision === 'approved' ? (
            <ShieldCheck className="w-5 h-5 shrink-0 text-accent-primary" aria-hidden="true" />
          ) : decision === 'rejected' ? (
            <ShieldX className="w-5 h-5 shrink-0 text-foreground-secondary" aria-hidden="true" />
          ) : (
            <ShieldAlert
              className={`w-5 h-5 shrink-0 ${isCritical ? 'text-accent-error' : 'text-foreground'}`}
              aria-hidden="true"
            />
          )}
          <span className="text-xs font-semibold uppercase tracking-wider text-foreground">
            {decision === 'approved'
              ? t(lang, 'approval.approvedTitle')
              : decision === 'rejected'
              ? t(lang, 'approval.rejectedTitle')
              : t(lang, 'approval.pendingTitle')}
          </span>
        </div>

        <div className="flex items-center gap-2 min-w-0">
          <span
            className={`px-2 py-0.5 text-xs font-semibold uppercase rounded-full border ${riskBadgeClass}`}
          >
            {t(lang, 'approval.risk', { level: risk_level })}
          </span>
          <span className="text-xs text-foreground-muted font-mono truncate max-w-[10rem]" title={action_id}>
            {action_id}
          </span>
        </div>
      </div>

      {/* What will run, before the raw command */}
      <div className="mt-3 space-y-1.5">
        <div className="flex items-center gap-2 text-sm">
          {agent === 'db_agent' ? (
            <Database className="w-4 h-4 shrink-0 text-foreground-secondary" aria-hidden="true" />
          ) : (
            <Globe className="w-4 h-4 shrink-0 text-foreground-secondary" aria-hidden="true" />
          )}
          <span className="font-medium text-foreground">
            {agent === 'db_agent'
              ? t(lang, 'approval.agentDb')
              : t(lang, 'approval.agentIntegration')}{' '}
            ({action_type})
          </span>
        </div>
        <p className="text-sm font-medium text-foreground break-words">
          {payload.sql
            ? t(lang, 'approval.willRunSql')
            : t(lang, 'approval.willCall', { method: payload.method || 'POST', url: payload.url || '' })}
        </p>
        <p className="text-sm text-foreground-secondary leading-relaxed break-words">{description}</p>
      </div>

      {/* Payload / SQL Preview */}
      <div className="mt-3 relative rounded-lg bg-background border border-border p-3 font-mono text-xs overflow-x-auto text-foreground">
        <div className="flex justify-between items-center pb-1.5 mb-1.5 border-b border-border text-xs text-foreground-muted">
          <span>{t(lang, 'approval.commandDetails')}</span>
          <button
            type="button"
            onClick={() =>
              handleCopy(
                payload.sql ||
                  `${payload.method || ''} ${payload.url || ''}\n${JSON.stringify(
                    payload.payload || {},
                    null,
                    2
                  )}`
              )
            }
            className={`flex items-center gap-1 px-1.5 py-0.5 rounded hover:text-foreground text-xs cursor-pointer ${focusRing}`}
          >
            {copied ? <Check className="w-3.5 h-3.5 text-accent-primary" aria-hidden="true" /> : <Copy className="w-3.5 h-3.5" aria-hidden="true" />}
            <span>{copied ? t(lang, 'approval.copied') : t(lang, 'approval.copy')}</span>
          </button>
        </div>

        {payload.sql ? (
          <div className="whitespace-pre-wrap break-all">{payload.sql}</div>
        ) : (
          <div className="space-y-1">
            <div className="flex items-center gap-1.5">
              <span className="px-1.5 py-0.5 rounded text-xs font-bold bg-surface-raised text-foreground border border-border">
                {payload.method || 'POST'}
              </span>
              <span className="break-all">{payload.url}</span>
            </div>
            {payload.payload && (
              <pre className="text-foreground-secondary text-xs mt-1 overflow-x-auto">
                {JSON.stringify(payload.payload, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>

      {/* Execution Result Banner (After Decision) */}
      {executionResult && (
        <div role="status" aria-live="polite" className="mt-3 p-3 rounded-lg bg-background border border-border text-sm text-foreground">
          <p className="font-semibold text-xs text-foreground mb-1">
            {t(lang, 'approval.resultAfter')}
          </p>
          <div className="whitespace-pre-wrap text-xs text-foreground-secondary break-words">
            {executionResult}
          </div>
        </div>
      )}

      {/* Two-person approval: the requester cannot decide; they wait for the answer of another approver */}
      {decision === null && waitingForOther && (
        <p role="status" aria-live="polite" className="mt-3 flex items-center gap-2 border-t border-border pt-3 text-sm text-foreground-secondary">
          {!expired && <Loader2 className="w-4 h-4 shrink-0 animate-spin" aria-hidden="true" />}
          {expired ? t(lang, 'approval.expired') : t(lang, 'approval.waitingOther')}
        </p>
      )}

      {/* Action Decision Controls */}
      {decision === null && !waitingForOther && (
        <div className="mt-3 pt-3 border-t border-border space-y-2">
          {showReasonInput && (
            <div className="space-y-1 animate-fade-in">
              <label htmlFor={`reject-reason-${action_id}`} className="text-xs text-foreground-secondary block">
                {t(lang, 'approval.reasonLabel')}
              </label>
              <input
                id={`reject-reason-${action_id}`}
                type="text"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder={t(lang, 'approval.reasonPlaceholder')}
                className="w-full text-sm px-3 py-2 rounded-lg bg-background border border-border-strong text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-accent-primary focus:ring-2 focus:ring-accent-primary/20"
              />
            </div>
          )}

          {confirmingApprove && (
            <p role="status" aria-live="polite" className="text-xs font-medium text-accent-error">
              {t(lang, 'approval.criticalHint')}
            </p>
          )}

          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleDecision('reject')}
              className={`inline-flex items-center justify-center gap-1.5 min-h-9 px-4 py-2 rounded-lg text-sm font-semibold text-foreground border border-border-strong hover:bg-surface-raised transition-colors disabled:opacity-50 cursor-pointer ${focusRing}`}
            >
              {isSubmitting && showReasonInput ? (
                <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
              ) : (
                <X className="w-4 h-4" aria-hidden="true" />
              )}
              <span>{showReasonInput ? t(lang, 'approval.confirmReject') : t(lang, 'approval.reject')}</span>
            </button>

            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleDecision('approve')}
              className={`inline-flex items-center justify-center gap-1.5 min-h-9 px-4 py-2 rounded-lg text-sm font-semibold text-white transition-colors disabled:opacity-50 cursor-pointer ${focusRing} ${
                confirmingApprove ? 'bg-accent-error hover:opacity-90' : 'bg-accent-primary hover:bg-accent-primary-hover'
              }`}
            >
              {isSubmitting && !showReasonInput ? (
                <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
              ) : (
                <Check className="w-4 h-4" aria-hidden="true" />
              )}
              <span>{confirmingApprove ? t(lang, 'approval.confirmApprove') : t(lang, 'approval.approve')}</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
