'use client';

import React, { useState } from 'react';
import {
  Compass,
  Cpu,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Brain,
} from 'lucide-react';
import { t, useLang } from '../lib/i18n';

interface AgentThoughtStepperProps {
  pevEvents?: {
    plan?: { plan: string; target_agent: string };
    executing?: { target_agent: string; execution_result: string };
    verifying?: { is_verified: boolean; verifier_feedback: string; retry_count: number };
    final_response?: { response: string; target_agent: string; is_verified: boolean };
    error?: string;
  };
  isStreaming?: boolean;
}

export const AgentThoughtStepper: React.FC<AgentThoughtStepperProps> = ({
  pevEvents,
  isStreaming,
}) => {
  const [lang] = useLang();
  const [isExpanded, setIsExpanded] = useState(false);

  if (!pevEvents && !isStreaming) return null;

  const plan = pevEvents?.plan;
  const executing = pevEvents?.executing;
  const verifying = pevEvents?.verifying;
  const error = pevEvents?.error;

  const hasPlan = Boolean(plan);
  const hasExecuting = Boolean(executing);
  const hasVerifying = Boolean(verifying);

  let currentStatusText = t(lang, 'pev.status.init');
  if (isStreaming) {
    if (!hasPlan) currentStatusText = t(lang, 'thought.status.planning');
    else if (!hasExecuting) currentStatusText = t(lang, 'thought.status.delegating', { agent: plan?.target_agent || 'Executor' });
    else if (!hasVerifying) currentStatusText = t(lang, 'thought.status.validating');
  } else {
    currentStatusText = t(lang, 'thought.status.done');
  }

  return (
    <div className="my-3 border border-border rounded-xl bg-surface shadow-xs overflow-hidden text-xs transition-colors">
      {/* Header bar */}
      <div
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center justify-between px-4 py-2.5 bg-surface-raised hover:bg-surface-overlay/30 cursor-pointer transition-colors border-b border-border"
      >
        <div className="flex items-center space-x-2.5">
          <Brain className={`w-4 h-4 text-accent-primary ${isStreaming ? 'animate-pulse' : ''}`} />
          <span className="font-bold text-accent-primary">PEV Loop:</span>
          <span className="text-foreground-muted font-medium italic">{currentStatusText}</span>
        </div>

        <div className="flex items-center space-x-2">
          {isStreaming ? (
            <span className="flex items-center space-x-1 bg-accent-planner/10 text-accent-planner border border-accent-planner/20 px-2 py-0.5 rounded-full font-bold text-2xs animate-pulse">
              <Loader2 className="w-3 h-3 animate-spin" />
              <span>{t(lang, 'pev.badge.active')}</span>
            </span>
          ) : (
            <span className="flex items-center space-x-1 bg-accent-verifier/10 text-accent-verifier border border-accent-verifier/20 px-2 py-0.5 rounded-full font-bold text-2xs">
              <CheckCircle2 className="w-3 h-3" />
              <span>{t(lang, 'thought.verified')}</span>
            </span>
          )}
          <button className="text-foreground-muted hover:text-foreground cursor-pointer transition-colors" aria-label={t(lang, 'thought.toggle')}>
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Timeline Nodes Bar */}
      <div className="px-4 py-3 bg-surface flex items-center justify-around gap-2">
        {/* Step 1: Planner */}
        <div className="flex items-center space-x-2">
          <div className={`w-7 h-7 rounded-full flex items-center justify-center font-bold transition-all ${
            hasPlan
              ? 'bg-accent-planner text-white shadow-xs'
              : isStreaming
              ? 'bg-accent-planner/10 text-accent-planner animate-pulse'
              : 'bg-surface-raised text-foreground-muted border border-border'
          }`}>
            <Compass className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="font-semibold text-foreground">1. Plan</div>
            <div className="text-2xs font-mono text-foreground-muted">
              {plan?.target_agent ? t(lang, 'pev.target', { agent: plan.target_agent }) : t(lang, 'thought.strategy')}
            </div>
          </div>
        </div>

        <div className={`h-0.5 flex-1 max-w-[40px] rounded-full ${hasPlan ? 'bg-accent-planner' : 'bg-border'}`} />

        {/* Step 2: Executor */}
        <div className="flex items-center space-x-2">
          <div className={`w-7 h-7 rounded-full flex items-center justify-center font-bold transition-all ${
            hasExecuting
              ? 'bg-accent-executor text-white shadow-xs'
              : isStreaming && hasPlan
              ? 'bg-accent-executor/10 text-accent-executor animate-pulse'
              : 'bg-surface-raised text-foreground-muted border border-border'
          }`}>
            <Cpu className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="font-semibold text-foreground">2. Execute</div>
            <div className="text-2xs font-mono text-foreground-muted">
              {executing?.target_agent || 'Process'}
            </div>
          </div>
        </div>

        <div className={`h-0.5 flex-1 max-w-[40px] rounded-full ${hasExecuting ? 'bg-accent-executor' : 'bg-border'}`} />

        {/* Step 3: Verifier */}
        <div className="flex items-center space-x-2">
          <div className={`w-7 h-7 rounded-full flex items-center justify-center font-bold transition-all ${
            hasVerifying
              ? verifying?.is_verified
                ? 'bg-accent-verifier text-white shadow-xs'
                : 'bg-accent-error text-white shadow-xs'
              : isStreaming && hasExecuting
              ? 'bg-accent-verifier/10 text-accent-verifier animate-pulse'
              : 'bg-surface-raised text-foreground-muted border border-border'
          }`}>
            <ShieldCheck className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="font-semibold text-foreground">3. Verify</div>
            <div className="text-2xs font-mono text-foreground-muted">
              {verifying ? (verifying.is_verified ? t(lang, 'thought.passed') : t(lang, 'thought.feedbackLoop')) : t(lang, 'thought.quality')}
            </div>
          </div>
        </div>
      </div>

      {/* Expandable Detail Section */}
      {isExpanded && (
        <div className="p-4 space-y-3 bg-surface-raised/50 border-t border-border font-mono text-2xs text-foreground-secondary animate-fade-in">
          <div className="bg-surface p-3 rounded-lg border border-border">
            <div className="font-bold text-accent-planner mb-1 flex items-center gap-1.5 font-sans text-xs">
              <Compass className="w-3.5 h-3.5" /> {t(lang, 'thought.plannerOutput')}
            </div>
            {plan ? (
              <p className="whitespace-pre-wrap">{plan.plan}</p>
            ) : isStreaming && !hasPlan ? (
              <p className="italic text-foreground-muted flex items-center gap-1.5">
                <Loader2 className="w-3 h-3 animate-spin text-accent-planner" />
                {t(lang, 'pev.planner.working')}
              </p>
            ) : (
              <p className="italic text-foreground-muted">{t(lang, 'pev.waiting')}</p>
            )}
          </div>

          <div className="bg-surface p-3 rounded-lg border border-border">
            <div className="font-bold text-accent-executor mb-1 flex items-center gap-1.5 font-sans text-xs">
              <Cpu className="w-3.5 h-3.5" /> Executor [{executing?.target_agent || plan?.target_agent || t(lang, 'pev.agentSpecialized')}]:
            </div>
            {executing ? (
              <p className="whitespace-pre-wrap max-h-40 overflow-y-auto">{executing.execution_result.slice(0, 500)}...</p>
            ) : isStreaming && hasPlan && !hasExecuting ? (
              <p className="italic text-foreground-muted flex items-center gap-1.5">
                <Loader2 className="w-3 h-3 animate-spin text-accent-executor" />
                {t(lang, 'pev.executor.working', { agent: plan?.target_agent || t(lang, 'pev.agentSpecialized') })}
              </p>
            ) : (
              <p className="italic text-foreground-muted">{t(lang, 'pev.waiting')}</p>
            )}
          </div>

          <div className="bg-surface p-3 rounded-lg border border-border">
            <div className="font-bold text-accent-verifier mb-1 flex items-center gap-1.5 font-sans text-xs">
              <ShieldCheck className="w-3.5 h-3.5" /> {t(lang, 'thought.verifierReport')}
            </div>
            {verifying ? (
              <p className="whitespace-pre-wrap">
                {t(lang, 'thought.qualityLabel')} <span className={verifying.is_verified ? 'text-accent-verifier font-bold' : 'text-accent-error font-bold'}>
                  {verifying.is_verified ? t(lang, 'thought.verifiedPassed') : t(lang, 'thought.rejected')}
                </span>
                {verifying.verifier_feedback && ` | ${t(lang, 'thought.feedbackLabel', { text: verifying.verifier_feedback })}`}
              </p>
            ) : isStreaming && hasExecuting && !hasVerifying ? (
              <p className="italic text-foreground-muted flex items-center gap-1.5">
                <Loader2 className="w-3 h-3 animate-spin text-accent-verifier" />
                {t(lang, 'pev.verifier.working')}
              </p>
            ) : (
              <p className="italic text-foreground-muted">{t(lang, 'pev.waiting')}</p>
            )}
          </div>

          {error && (
            <div className="bg-accent-error/5 p-3 rounded-lg border border-accent-error/20 text-accent-error flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
