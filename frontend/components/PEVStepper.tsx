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
  RotateCcw,
  ChevronRight,
} from 'lucide-react';
import { PEVStepData, PEVTrace, PEVTraceState } from '../lib/types';
import { Lang, t, useLang } from '../lib/i18n';

interface PEVStepperProps {
  pevStep?: PEVStepData;
  pevEvents?: {
    plan?: { plan: string; target_agent: string };
    executing?: { target_agent: string; execution_result: string };
    verifying?: { is_verified: boolean; verifier_feedback: string; retry_count: number };
    final_response?: { response: string; target_agent: string; is_verified: boolean; pev_trace?: PEVTrace };
    error?: string;
  };
  pevTrace?: PEVTrace;
  pevTraceState?: PEVTraceState;
  isStreaming?: boolean;
}

function getAgentPipelineSteps(lang: Lang, agentName?: string): string[] {
  const norm = (agentName || '').toLowerCase();
  if (norm.includes('data')) return ['EDA', t(lang, 'pev.pipe.layout'), t(lang, 'pev.pipe.charts')];
  if (norm.includes('rag')) return ['HyDE Document', 'Hybrid Search (pgvector)', 'TEI Reranker (Top 5)'];
  if (norm.includes('search')) return ['Tavily Web Search', 'Crawl4AI Content Extraction'];
  if (norm.includes('db')) return [t(lang, 'pev.pipe.sql'), t(lang, 'pev.pipe.mcp')];
  return [t(lang, 'pev.pipe.analyze'), t(lang, 'pev.pipe.tools'), t(lang, 'pev.pipe.compose')];
}

export const PEVStepper: React.FC<PEVStepperProps> = ({
  pevStep,
  pevEvents,
  pevTrace,
  pevTraceState,
  isStreaming,
}) => {
  const [lang] = useLang();
  const [isExpanded, setIsExpanded] = useState(false);

  if (!pevStep && !pevEvents && !pevTrace && !pevTraceState && !isStreaming) return null;

  // Resolve plan, executing, verifying data from state, events or pevTrace
  const planData = pevEvents?.plan || (pevTrace?.planner ? { plan: pevTrace.planner.plan_summary || '', target_agent: pevTrace.planner.target_agent || '' } : undefined);
  const execData = pevEvents?.executing || (pevTrace?.executor ? { target_agent: pevTrace.executor.agent_used || '', execution_result: pevTrace.executor.execution_summary || '' } : undefined);
  const verifyData = pevEvents?.verifying || (pevTrace?.verifier ? { is_verified: pevTrace.verifier.is_verified ?? true, verifier_feedback: pevTrace.verifier.verifier_feedback || '', retry_count: 0 } : undefined);
  const error = pevEvents?.error;

  const targetAgent =
    pevTraceState?.planner.targetAgent ||
    pevTraceState?.executor.agentName ||
    planData?.target_agent ||
    execData?.target_agent ||
    pevStep?.target ||
    pevTrace?.planner?.target_agent ||
    pevTrace?.executor?.agent_used;

  const planText = pevTraceState?.planner.plan || planData?.plan || pevTrace?.planner?.plan_summary || '';
  const execSummary = pevTraceState?.executor.outputSummary || execData?.execution_result || pevTrace?.executor?.execution_summary || '';
  const verifierFeedback = pevTraceState?.verifier.feedback || verifyData?.verifier_feedback || pevTrace?.verifier?.verifier_feedback || '';

  // Determine current step
  const currentStep = pevTraceState?.currentStep || pevStep?.step || (
    pevTrace || pevEvents?.verifying || verifyData !== undefined
      ? 'completed'
      : pevEvents?.executing || execData
      ? 'verifier'
      : pevEvents?.plan || planData
      ? 'executor'
      : isStreaming
      ? 'planner'
      : 'completed'
  );

  // Determine node statuses
  const plannerStatus: 'idle' | 'active' | 'completed' =
    pevTraceState?.planner.status === 'completed'
      ? 'completed'
      : pevTraceState?.planner.status === 'active'
      ? 'active'
      : Boolean(planText) || currentStep === 'executor' || currentStep === 'verifier' || currentStep === 'completed' || Boolean(pevTrace)
      ? 'completed'
      : currentStep === 'planner' && isStreaming
      ? 'active'
      : 'idle';

  const executorStatus: 'idle' | 'active' | 'completed' =
    pevTraceState?.executor.status === 'completed'
      ? 'completed'
      : pevTraceState?.executor.status === 'active'
      ? 'active'
      : Boolean(execSummary) || currentStep === 'verifier' || currentStep === 'completed' || Boolean(pevTrace)
      ? 'completed'
      : currentStep === 'executor' && isStreaming
      ? 'active'
      : 'idle';

  const isVerified =
    pevTraceState?.verifier.isVerified ??
    verifyData?.is_verified ??
    pevEvents?.final_response?.is_verified ??
    (pevTrace?.status ? pevTrace.status === 'Verified' : undefined) ??
    pevTrace?.verifier?.is_verified ??
    true;

  const verifierStatus: 'idle' | 'active' | 'completed' =
    pevTraceState?.verifier.status === 'completed'
      ? 'completed'
      : pevTraceState?.verifier.status === 'active'
      ? 'active'
      : currentStep === 'completed' || verifyData !== undefined || Boolean(pevTrace)
      ? 'completed'
      : currentStep === 'verifier' && isStreaming
      ? 'active'
      : 'idle';

  const isPlannerDone = plannerStatus === 'completed';
  const isExecutorDone = executorStatus === 'completed';
  const isVerifierDone = verifierStatus === 'completed';

  const isPlannerActive = plannerStatus === 'active';
  const isExecutorActive = executorStatus === 'active';
  const isVerifierActive = verifierStatus === 'active';

  const retryCount = pevTraceState?.verifier.retryCount ?? verifyData?.retry_count ?? 0;
  const isRetry = verifierStatus === 'completed' && !isVerified && retryCount > 0;
  const isAuditPassed = isVerified && !isRetry;

  // The step log the backend sends is not shown: its text is in one language, the interface text follows the user's choice
  let statusText = t(lang, 'pev.status.init');
  if (isStreaming) {
    if (isPlannerActive) statusText = t(lang, 'pev.status.planner');
    else if (isExecutorActive) statusText = t(lang, 'pev.status.executor', { agent: targetAgent || 'Agent' });
    else if (isVerifierActive) statusText = t(lang, 'pev.status.verifier');
  } else {
    statusText = isVerified ? t(lang, 'pev.status.verified') : t(lang, 'pev.status.review');
  }

  const pipelineSteps = getAgentPipelineSteps(lang, targetAgent);

  return (
    <div data-testid="pev-stepper" className="my-3 border border-border rounded-xl bg-surface shadow-xs overflow-hidden text-xs transition-colors duration-200">
      {/* Header Bar */}
      <div
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center justify-between px-4 py-2.5 bg-surface-raised hover:bg-surface-overlay/30 cursor-pointer transition-colors duration-150 border-b border-border"
      >
        <div className="flex items-center space-x-2.5 overflow-hidden min-w-0">
          <Brain className={`w-4 h-4 shrink-0 text-accent-primary ${isStreaming ? 'animate-pulse' : ''}`} />
          <span className="font-bold text-accent-primary shrink-0">{t(lang, 'pev.title')}</span>
          <span className="text-foreground-muted font-medium truncate">{statusText}</span>
        </div>

        <div className="flex items-center space-x-2 shrink-0">
          {isStreaming ? (
            <span className="flex items-center space-x-1 bg-accent-planner/10 text-accent-planner border border-accent-planner/20 px-2.5 py-0.5 rounded-full font-bold text-2xs animate-pulse">
              <Loader2 className="w-3 h-3 animate-spin" />
              <span>{t(lang, 'pev.badge.active')}</span>
            </span>
          ) : isVerified ? (
            <span className="flex items-center space-x-1 bg-accent-verifier/10 text-accent-verifier border border-accent-verifier/20 px-2.5 py-0.5 rounded-full font-bold text-2xs">
              <CheckCircle2 className="w-3 h-3" />
              <span>{t(lang, 'pev.badge.verified')}</span>
            </span>
          ) : (
            <span className="flex items-center space-x-1 bg-accent-error/10 text-accent-error border border-accent-error/20 px-2.5 py-0.5 rounded-full font-bold text-2xs">
              <AlertCircle className="w-3 h-3" />
              <span>{t(lang, 'pev.badge.unverified')}</span>
            </span>
          )}
          <button className="text-foreground-muted hover:text-foreground transition-colors duration-150 cursor-pointer" aria-label={t(lang, 'pev.toggle')}>
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Timeline Stepper Bar */}
      <div className="px-5 py-3.5 bg-surface flex items-center justify-between gap-3">
        {/* Step 1: Planner Node */}
        <div className="flex items-center gap-2.5 min-w-0">
          <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 transition-all duration-200 ${
            isPlannerDone
              ? 'bg-accent-planner text-white shadow-xs'
              : isPlannerActive
              ? 'bg-accent-planner/10 text-accent-planner ring-2 ring-accent-planner/30 animate-pulse-subtle'
              : 'bg-surface-raised text-foreground-muted border border-border'
          }`}>
            {isPlannerActive ? <Loader2 className="w-4 h-4 animate-spin" /> : isPlannerDone ? <CheckCircle2 className="w-4 h-4" /> : <Compass className="w-4 h-4" />}
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-foreground text-xs">1. Planner Node</div>
            <div className="text-xs text-foreground-muted truncate">
              {targetAgent ? `→ ${targetAgent}` : isPlannerActive ? t(lang, 'pev.planner.analyzing') : t(lang, 'pev.planner.idle')}
            </div>
          </div>
        </div>

        {/* Dynamic Flex Connector 1→2 */}
        <div className={`h-0.5 flex-1 max-w-[96px] rounded-full transition-colors duration-200 ${isPlannerDone ? 'bg-accent-planner' : 'bg-border'}`} />

        {/* Step 2: Executor Node */}
        <div className="flex items-center gap-2.5 min-w-0">
          <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 transition-all duration-200 ${
            isExecutorDone
              ? 'bg-accent-executor text-white shadow-xs'
              : isExecutorActive
              ? 'bg-accent-executor/10 text-accent-executor ring-2 ring-accent-executor/30 animate-pulse-subtle'
              : 'bg-surface-raised text-foreground-muted border border-border'
          }`}>
            {isExecutorActive ? <Loader2 className="w-4 h-4 animate-spin" /> : isExecutorDone ? <CheckCircle2 className="w-4 h-4" /> : <Cpu className="w-4 h-4" />}
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-foreground text-xs">2. Executor Node</div>
            <div className="text-xs text-foreground-muted truncate">
              {targetAgent || (isExecutorActive ? t(lang, 'pev.executor.running') : t(lang, 'pev.executor.idle'))}
            </div>
          </div>
        </div>

        {/* Dynamic Flex Connector 2→3 */}
        <div className={`h-0.5 flex-1 max-w-[96px] rounded-full transition-colors duration-200 ${isExecutorDone ? 'bg-accent-executor' : 'bg-border'}`} />

        {/* Step 3: Verifier Node */}
        <div className="flex items-center gap-2.5 min-w-0">
          <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 transition-all duration-200 ${
            isVerifierActive
              ? 'bg-accent-verifier/10 text-accent-verifier ring-2 ring-accent-verifier/30 animate-pulse-subtle'
              : isVerifierDone
              ? isVerified
                ? 'bg-accent-verifier text-white shadow-xs'
                : 'bg-accent-error text-white shadow-xs'
              : 'bg-surface-raised text-foreground-muted border border-border'
          }`}>
            {isVerifierActive ? <Loader2 className="w-4 h-4 animate-spin" /> : isVerifierDone ? (isVerified ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />) : <ShieldCheck className="w-4 h-4" />}
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-foreground text-xs">3. Verifier Node</div>
            <div className="text-xs text-foreground-muted truncate">
              {isVerifierDone ? (isVerified ? t(lang, 'pev.verifier.valid') : t(lang, 'pev.verifier.review')) : isVerifierActive ? t(lang, 'pev.verifier.checking') : t(lang, 'pev.verifier.idle')}
            </div>
          </div>
        </div>

        {/* Retry indicator */}
        {isRetry && (
          <div className="flex items-center gap-1 px-2 py-0.5 bg-accent-error/10 text-accent-error rounded-full text-2xs font-bold shrink-0">
            <RotateCcw className="w-3 h-3" />
            <span>{t(lang, 'pev.retry', { count: retryCount })}</span>
          </div>
        )}
      </div>

      {/* Expandable Detail Accordion (Live Activity Timeline Panel with Zero-CLS Grid Transition) */}
      <div className={`accordion-content ${isExpanded ? 'expanded' : ''}`}>
        <div className="accordion-inner">
          <div className="p-4 bg-surface-raised/30 border-t border-border text-xs font-mono space-y-4">
            {/* Section 1: Planner Node */}
            <div className="p-3.5 rounded-lg bg-surface border border-border shadow-xs space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-sans font-bold text-xs text-accent-planner">
                  <Compass className="w-4 h-4" />
                  <span>{t(lang, 'pev.section.planner')}</span>
                </div>
                {plannerStatus === 'completed' && targetAgent && (
                  <span className="px-2 py-0.5 rounded text-2xs font-semibold bg-accent-planner/10 text-accent-planner border border-accent-planner/20">
                    {t(lang, 'pev.target', { agent: targetAgent })}
                  </span>
                )}
              </div>

              {plannerStatus === 'active' ? (
                <div className="flex items-center gap-2.5 py-1.5 text-foreground-secondary">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-accent-planner shrink-0" />
                  <span>{t(lang, 'pev.planner.working')}</span>
                </div>
              ) : plannerStatus === 'completed' ? (
                <div className="space-y-1.5 pt-0.5">
                  {planText ? (
                    <div className="p-2.5 rounded bg-surface-raised border border-border text-foreground-secondary whitespace-pre-wrap leading-relaxed">
                      {planText}
                    </div>
                  ) : (
                    <div className="text-foreground-muted italic">
                      {t(lang, 'pev.planner.planned', { agent: targetAgent || 'Agent' })}
                    </div>
                  )}
                </div>
              ) : (
                <div className="py-1 text-foreground-muted italic">
                  {t(lang, 'pev.waiting')}
                </div>
              )}
            </div>

            {/* Section 2: Executor Node */}
            <div className="p-3.5 rounded-lg bg-surface border border-border shadow-xs space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-sans font-bold text-xs text-accent-executor">
                  <Cpu className="w-4 h-4" />
                  <span>{t(lang, 'pev.section.executor')}</span>
                </div>
                {executorStatus !== 'idle' && targetAgent && (
                  <span className="px-2 py-0.5 rounded text-2xs font-semibold bg-accent-executor/10 text-accent-executor border border-accent-executor/20">
                    {t(lang, 'pev.agentLabel', { agent: targetAgent })}
                  </span>
                )}
              </div>

              {/* Pipeline subtasks */}
              {(executorStatus === 'active' || executorStatus === 'completed') && (
                <div className="flex items-center gap-1.5 flex-wrap py-1 text-2xs font-mono">
                  {pipelineSteps.map((step, idx) => (
                    <React.Fragment key={step}>
                      <span className={`px-2 py-0.5 rounded border transition-colors ${
                        executorStatus === 'completed'
                          ? 'bg-accent-executor/10 text-accent-executor border-accent-executor/20'
                          : idx === 0
                          ? 'bg-accent-executor/15 text-accent-executor border-accent-executor/30 animate-pulse'
                          : 'bg-surface-raised text-foreground-muted border-border'
                      }`}>
                        {step}
                      </span>
                      {idx < pipelineSteps.length - 1 && (
                        <ChevronRight className="w-3 h-3 text-foreground-muted shrink-0" />
                      )}
                    </React.Fragment>
                  ))}
                </div>
              )}

              {executorStatus === 'active' ? (
                <div className="flex items-center gap-2.5 py-1.5 text-foreground-secondary">
                  <span className="relative flex h-2.5 w-2.5 shrink-0">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-executor opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-accent-executor"></span>
                  </span>
                  <span>{t(lang, 'pev.executor.working', { agent: targetAgent || t(lang, 'pev.agentSpecialized') })}</span>
                </div>
              ) : executorStatus === 'completed' ? (
                <div className="space-y-1.5 pt-0.5">
                  {execSummary ? (
                    <div className="p-2.5 rounded bg-surface-raised border border-border text-foreground-secondary max-h-36 overflow-y-auto whitespace-pre-wrap leading-relaxed">
                      {execSummary}
                    </div>
                  ) : (
                    <div className="text-foreground-muted italic">
                      {t(lang, 'pev.executor.done', { agent: targetAgent || 'Executor' })}
                    </div>
                  )}
                </div>
              ) : (
                <div className="py-1 text-foreground-muted italic">
                  {t(lang, 'pev.waiting')}
                </div>
              )}
            </div>

            {/* Section 3: Verifier Node */}
            <div className="p-3.5 rounded-lg bg-surface border border-border shadow-xs space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 font-sans font-bold text-xs text-accent-verifier">
                  <ShieldCheck className="w-4 h-4" />
                  <span>{t(lang, 'pev.section.verifier')}</span>
                </div>
                {verifierStatus === 'completed' && (
                  isAuditPassed ? (
                    <span className="px-2 py-0.5 rounded text-2xs font-semibold bg-accent-verifier/10 text-accent-verifier border border-accent-verifier/20 flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" />
                      <span>{t(lang, 'pev.verifier.passed')}</span>
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded text-2xs font-semibold bg-accent-error/10 text-accent-error border border-accent-error/20 flex items-center gap-1">
                      <RotateCcw className="w-3 h-3" />
                      <span>{t(lang, 'pev.verifier.retryLoop', { count: retryCount || 1 })}</span>
                    </span>
                  )
                )}
              </div>

              {verifierStatus === 'active' ? (
                <div className="flex items-center gap-2.5 py-1.5 text-foreground-secondary">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-accent-verifier shrink-0" />
                  <span>{t(lang, 'pev.verifier.working')}</span>
                </div>
              ) : verifierStatus === 'completed' ? (
                <div className="space-y-1.5 pt-0.5">
                  {verifierFeedback ? (
                    <div className="p-2.5 rounded bg-surface-raised border border-border text-foreground-secondary whitespace-pre-wrap leading-relaxed">
                      <span className="font-semibold text-accent-verifier">{t(lang, 'pev.verifier.criteria')}</span>
                      {verifierFeedback}
                    </div>
                  ) : (
                    <div className="text-foreground-muted italic">
                      {t(lang, 'pev.verifier.clean')}
                    </div>
                  )}
                </div>
              ) : (
                <div className="py-1 text-foreground-muted italic">
                  {t(lang, 'pev.waiting')}
                </div>
              )}
            </div>

            {/* Error Banner */}
            {error && (
              <div className="p-3 bg-accent-error/10 border border-accent-error/20 rounded-lg text-accent-error flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
