'use client';

import React, { useState } from 'react';
import { HumanApprovalRequest } from '@/lib/types';
import {
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Check,
  X,
  AlertTriangle,
  Loader2,
  Database,
  Globe,
  Copy,
  ChevronDown,
} from 'lucide-react';

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
  const [decision, setDecision] = useState<'approved' | 'rejected' | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [showReasonInput, setShowReasonInput] = useState(false);
  const [copied, setCopied] = useState(false);
  const [executionResult, setExecutionResult] = useState<string | null>(null);

  const { action_id, agent, action_type, description, payload, risk_level } =
    approvalRequest;

  const isCritical = risk_level === 'critical';
  const isHigh = risk_level === 'high';

  const riskBadgeClass = isCritical
    ? 'bg-red-500/15 text-red-400 border-red-500/30'
    : isHigh
    ? 'bg-amber-500/15 text-amber-400 border-amber-500/30'
    : 'bg-blue-500/15 text-blue-400 border-blue-500/30';

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDecision = async (userDecision: 'approve' | 'reject') => {
    if (userDecision === 'reject' && !showReasonInput) {
      setShowReasonInput(true);
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await fetch('/api/chat/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          action_id,
          decision: userDecision,
          feedback: rejectReason.trim() || undefined,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || data.message || 'Lỗi khi gửi quyết định phê duyệt');
      }

      setDecision(userDecision === 'approve' ? 'approved' : 'rejected');
      const responseText = data.response || data.message || '';
      setExecutionResult(responseText);
      if (onDecisionSubmitted) {
        onDecisionSubmitted(action_id, userDecision, responseText);
      }
    } catch (err: any) {
      alert(`Lỗi phê duyệt: ${err.message}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className={`my-3 p-4 rounded-xl border transition-all duration-200 ${
        decision === 'approved'
          ? 'bg-emerald-950/20 border-emerald-500/30'
          : decision === 'rejected'
          ? 'bg-red-950/20 border-red-500/30'
          : isCritical
          ? 'bg-surface-elevated/95 border-red-500/40 shadow-lg shadow-red-950/20'
          : 'bg-surface-elevated/95 border-amber-500/40 shadow-lg shadow-amber-950/20'
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 pb-3 border-b border-border/40">
        <div className="flex items-center gap-2">
          {decision === 'approved' ? (
            <ShieldCheck className="w-5 h-5 text-emerald-400" />
          ) : decision === 'rejected' ? (
            <ShieldX className="w-5 h-5 text-red-400" />
          ) : (
            <ShieldAlert
              className={`w-5 h-5 ${
                isCritical ? 'text-red-400 animate-pulse' : 'text-amber-400'
              }`}
            />
          )}
          <span className="text-xs font-semibold uppercase tracking-wider text-foreground">
            {decision === 'approved'
              ? 'Đã Phê Duyệt & Thực Thi'
              : decision === 'rejected'
              ? 'Tác Vụ Đã Bị Từ Chối'
              : 'Xác Nhận Bảo Mật (HITL Gate)'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`px-2 py-0.5 text-[10px] font-semibold uppercase rounded-full border ${riskBadgeClass}`}
          >
            Mức Độ: {risk_level}
          </span>
          <span className="text-[10px] text-foreground-muted font-mono">
            {action_id}
          </span>
        </div>
      </div>

      {/* Description & Metadata */}
      <div className="mt-3 text-xs text-foreground-muted space-y-1.5">
        <div className="flex items-center gap-2">
          {agent === 'db_agent' ? (
            <Database className="w-3.5 h-3.5 text-accent-primary" />
          ) : (
            <Globe className="w-3.5 h-3.5 text-accent-secondary" />
          )}
          <span className="font-medium text-foreground">
            {agent === 'db_agent'
              ? 'Database Specialist'
              : 'Integration Specialist'}{' '}
            ({action_type})
          </span>
        </div>
        <p className="text-foreground/90 text-xs leading-relaxed">{description}</p>
      </div>

      {/* Payload / SQL Preview */}
      <div className="mt-3 relative rounded-lg bg-surface-base border border-border/50 p-2.5 font-mono text-[11px] overflow-x-auto text-foreground/90">
        <div className="flex justify-between items-center pb-1 mb-1 border-b border-border/30 text-[10px] text-foreground-muted">
          <span>Chi tiết lệnh chuẩn bị thực thi:</span>
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
            className="flex items-center gap-1 hover:text-foreground text-[10px] cursor-pointer"
          >
            {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
            <span>{copied ? 'Đã chép' : 'Sao chép'}</span>
          </button>
        </div>

        {payload.sql ? (
          <div className="text-emerald-400 whitespace-pre-wrap break-all">
            {payload.sql}
          </div>
        ) : (
          <div className="space-y-1">
            <div className="flex items-center gap-1.5">
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300">
                {payload.method || 'POST'}
              </span>
              <span className="text-foreground/90 break-all">{payload.url}</span>
            </div>
            {payload.payload && (
              <pre className="text-foreground-muted text-[10px] mt-1 overflow-x-auto">
                {JSON.stringify(payload.payload, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>

      {/* Execution Result Banner (After Decision) */}
      {executionResult && (
        <div className="mt-3 p-2.5 rounded-lg bg-surface-base/80 border border-border/40 text-xs text-foreground/90">
          <p className="font-semibold text-[11px] text-foreground mb-1">
            Kết quả sau phản hồi:
          </p>
          <div className="whitespace-pre-wrap text-[11px] text-foreground-muted">
            {executionResult}
          </div>
        </div>
      )}

      {/* Action Decision Controls */}
      {decision === null && (
        <div className="mt-3 pt-2.5 border-t border-border/30 space-y-2">
          {showReasonInput && (
            <div className="space-y-1 animate-in fade-in duration-150">
              <label className="text-[11px] text-foreground-muted block">
                Lý do từ chối (không bắt buộc):
              </label>
              <input
                type="text"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="Nhập lý do hủy lệnh..."
                className="w-full text-xs px-2.5 py-1.5 rounded-lg bg-surface-base border border-border/60 text-foreground placeholder:text-foreground-muted/60 focus:outline-none focus:border-red-500/50"
              />
            </div>
          )}

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleDecision('reject')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-red-400 border border-red-500/30 hover:bg-red-500/10 transition-colors disabled:opacity-50 cursor-pointer"
            >
              {isSubmitting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <X className="w-3.5 h-3.5" />
              )}
              <span>{showReasonInput ? 'Xác nhận Từ Chối' : 'Từ Chối'}</span>
            </button>

            <button
              type="button"
              disabled={isSubmitting}
              onClick={() => handleDecision('approve')}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium text-white bg-emerald-600 hover:bg-emerald-500 shadow-sm transition-colors disabled:opacity-50 cursor-pointer"
            >
              {isSubmitting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Check className="w-3.5 h-3.5" />
              )}
              <span>Phê Duyệt & Thực Thi</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
