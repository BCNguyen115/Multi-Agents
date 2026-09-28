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

function getAgentPipelineSteps(agentName?: string): { name: string; desc?: string }[] {
  const norm = (agentName || '').toLowerCase();
  if (norm.includes('data')) {
    return [
      { name: 'EDA', desc: 'Khám phá dữ liệu' },
      { name: 'Tạo Layout', desc: 'Thiết kế bố cục' },
      { name: 'Dựng Biểu Đồ', desc: 'Trực quan hóa' },
    ];
  }
  if (norm.includes('rag')) {
    return [
      { name: 'HyDE Document', desc: 'Tổng hợp tài liệu giả định' },
      { name: 'Hybrid Search (pgvector)', desc: 'Truy vấn vector kết hợp' },
      { name: 'TEI Reranker (Top 5)', desc: 'Tái xếp hạng độ liên quan' },
    ];
  }
  if (norm.includes('search')) {
    return [
      { name: 'Tavily Web Search', desc: 'Truy vấn web thời gian thực' },
      { name: 'Crawl4AI Content Extraction', desc: 'Trích xuất bài viết sâu' },
    ];
  }
  if (norm.includes('db')) {
    return [
      { name: 'Sinh câu lệnh SQL Read-Only', desc: 'Tạo truy vấn đọc an toàn' },
      { name: 'Thực thi qua MCP', desc: 'Truy vấn cơ sở dữ liệu' },
    ];
  }
  return [
    { name: 'Phân tích tác vụ', desc: 'Nhận diện nhiệm vụ' },
    { name: 'Thực thi công cụ', desc: 'Xử lý dữ liệu' },
    { name: 'Tổng hợp kết quả', desc: 'Đóng gói phản hồi' },
  ];
}

export const PEVStepper: React.FC<PEVStepperProps> = ({
  pevStep,
  pevEvents,
  pevTrace,
  pevTraceState,
  isStreaming,
}) => {
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

  let statusText = 'Initializing PEV Loop...';
  if (pevStep?.logs) {
    statusText = pevStep.logs;
  } else if (isStreaming) {
    if (isPlannerActive) statusText = 'Planner analyzing request...';
    else if (isExecutorActive) statusText = `Executor [${targetAgent || 'Agent'}] processing...`;
    else if (isVerifierActive) statusText = 'Verifier validating response...';
  } else {
    statusText = isVerified ? 'PEV Loop completed (Verified)' : 'PEV Loop completed (Needs review)';
  }

  const pipelineSteps = getAgentPipelineSteps(targetAgent);

  return (
    <div data-testid="pev-stepper" className="my-3 border border-border rounded-xl bg-surface shadow-xs overflow-hidden text-xs transition-colors duration-200">
      {/* Header Bar */}
      <div
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center justify-between px-4 py-2.5 bg-surface-raised hover:bg-surface-overlay/30 cursor-pointer transition-colors duration-150 border-b border-border"
      >
        <div className="flex items-center space-x-2.5 overflow-hidden min-w-0">
          <Brain className={`w-4 h-4 shrink-0 text-accent-primary ${isStreaming ? 'animate-pulse' : ''}`} />
          <span className="font-bold text-accent-primary shrink-0">PEV Loop Stepper: Core Reasoning Workflow</span>
          <span className="text-foreground-muted font-medium truncate">{statusText}</span>
        </div>

        <div className="flex items-center space-x-2 shrink-0">
          {isStreaming ? (
            <span className="flex items-center space-x-1 bg-accent-planner/10 text-accent-planner border border-accent-planner/20 px-2.5 py-0.5 rounded-full font-bold text-[10px] animate-pulse">
              <Loader2 className="w-3 h-3 animate-spin" />
              <span>Active</span>
            </span>
          ) : isVerified ? (
            <span className="flex items-center space-x-1 bg-accent-verifier/10 text-accent-verifier border border-accent-verifier/20 px-2.5 py-0.5 rounded-full font-bold text-[10px]">
              <CheckCircle2 className="w-3 h-3" />
              <span>(Verified)</span>
            </span>
          ) : (
            <span className="flex items-center space-x-1 bg-accent-error/10 text-accent-error border border-accent-error/20 px-2.5 py-0.5 rounded-full font-bold text-[10px]">
              <AlertCircle className="w-3 h-3" />
              <span>(Unverified)</span>
            </span>
          )}
          <button className="text-foreground-muted hover:text-foreground transition-colors duration-150 cursor-pointer">
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
              ? 'bg-accent-planner/10 text-accent-planner ring-2 ring-accent-planner/40 animate-pulse-glow-amber'
              : 'bg-surface-raised text-foreground-muted border border-border'
          }`}>
            {isPlannerActive ? <Loader2 className="w-4 h-4 animate-spin" /> : isPlannerDone ? <CheckCircle2 className="w-4 h-4" /> : <Compass className="w-4 h-4" />}
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-foreground text-xs">1. Planner Node</div>
            <div className="text-xs text-foreground-muted truncate">
              {targetAgent ? `→ ${targetAgent}` : isPlannerActive ? 'Đang phân tích...' : 'Chiến lược'}
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
              ? 'bg-accent-executor/10 text-accent-executor ring-2 ring-accent-executor/40 animate-pulse-glow'
              : 'bg-surface-raised text-foreground-muted border border-border'
          }`}>
            {isExecutorActive ? <Loader2 className="w-4 h-4 animate-spin" /> : isExecutorDone ? <CheckCircle2 className="w-4 h-4" /> : <Cpu className="w-4 h-4" />}
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-foreground text-xs">2. Executor Node</div>
            <div className="text-xs text-foreground-muted truncate">
              {targetAgent || (isExecutorActive ? 'Đang chạy...' : 'Xử lý')}
            </div>
          </div>
        </div>

        {/* Dynamic Flex Connector 2→3 */}
        <div className={`h-0.5 flex-1 max-w-[96px] rounded-full transition-colors duration-200 ${isExecutorDone ? 'bg-accent-executor' : 'bg-border'}`} />

        {/* Step 3: Verifier Node */}
        <div className="flex items-center gap-2.5 min-w-0">
          <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 transition-all duration-200 ${
            isVerifierActive
              ? 'bg-accent-verifier/10 text-accent-verifier ring-2 ring-accent-verifier/40 animate-pulse-glow-emerald'
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
              {isVerifierDone ? (isVerified ? '100% Hợp lệ' : 'Cần rà soát') : isVerifierActive ? 'Đối soát...' : 'Kiểm định'}
            </div>
          </div>
        </div>

        {/* Retry indicator */}
        {isRetry && (
          <div className="flex items-center gap-1 px-2 py-0.5 bg-accent-error/10 text-accent-error rounded-full text-[10px] font-bold shrink-0">
            <RotateCcw className="w-3 h-3" />
            <span>Retry #{retryCount}</span>
          </div>
        )}
      </div>

      {/* Expandable Detail Accordion (Live Activity Timeline Panel) */}
      {isExpanded && (
        <div className="p-4 bg-zinc-50 dark:bg-zinc-900/70 border-t border-zinc-200 dark:border-zinc-800 text-xs font-mono space-y-4 animate-fade-in">
          {/* Mục 1: Planner Node (Phân tích & Lập Kế Hoạch) */}
          <div className="p-3.5 rounded-lg bg-white dark:bg-zinc-950/60 border border-zinc-200 dark:border-zinc-800 shadow-2xs space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-sans font-bold text-xs text-amber-600 dark:text-amber-400">
                <Compass className="w-4 h-4" />
                <span>Planner Node (Phân tích &amp; Lập Kế Hoạch)</span>
              </div>
              {plannerStatus === 'completed' && targetAgent && (
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                  Target: {targetAgent}
                </span>
              )}
            </div>

            {plannerStatus === 'active' ? (
              <div className="flex items-center gap-2.5 py-1.5 text-zinc-600 dark:text-zinc-300">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-500 shrink-0" />
                <span>Đang phân tích câu hỏi, nạp bộ nhớ dài hạn và lựa chọn Agent phù hợp...</span>
              </div>
            ) : plannerStatus === 'completed' ? (
              <div className="space-y-1.5 pt-0.5">
                {planText ? (
                  <div className="p-2.5 rounded bg-zinc-50 dark:bg-zinc-900/80 border border-zinc-200 dark:border-zinc-800/80 text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap leading-relaxed">
                    {planText}
                  </div>
                ) : (
                  <div className="text-zinc-500 dark:text-zinc-400 italic">
                    Kế hoạch đã được xác lập và điều phối tới [{targetAgent || 'Agent'}].
                  </div>
                )}
              </div>
            ) : (
              <div className="py-1 text-zinc-400 dark:text-zinc-600 italic">
                Chờ thực thi...
              </div>
            )}
          </div>

          {/* Mục 2: Executor Node (Thực Thi Nhiệm Vụ) */}
          <div className="p-3.5 rounded-lg bg-white dark:bg-zinc-950/60 border border-zinc-200 dark:border-zinc-800 shadow-2xs space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-sans font-bold text-xs text-blue-600 dark:text-blue-400">
                <Cpu className="w-4 h-4" />
                <span>Executor Node (Thực Thi Nhiệm Vụ)</span>
              </div>
              {executorStatus !== 'idle' && targetAgent && (
                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20">
                  Agent: {targetAgent}
                </span>
              )}
            </div>

            {/* Pipeline subtasks */}
            {(executorStatus === 'active' || executorStatus === 'completed') && (
              <div className="flex items-center gap-1.5 flex-wrap py-1 text-[11px]">
                {pipelineSteps.map((step, idx) => (
                  <React.Fragment key={step.name}>
                    <span className={`px-2 py-0.5 rounded border transition-colors ${
                      executorStatus === 'completed'
                        ? 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20'
                        : idx === 0
                        ? 'bg-blue-500/15 text-blue-600 dark:text-blue-300 border-blue-500/30 animate-pulse'
                        : 'bg-zinc-100 dark:bg-zinc-900 text-zinc-400 dark:text-zinc-500 border-zinc-200 dark:border-zinc-800'
                    }`}>
                      {step.name}
                    </span>
                    {idx < pipelineSteps.length - 1 && (
                      <ChevronRight className="w-3 h-3 text-zinc-400 dark:text-zinc-600 shrink-0" />
                    )}
                  </React.Fragment>
                ))}
              </div>
            )}

            {executorStatus === 'active' ? (
              <div className="flex items-center gap-2.5 py-1.5 text-zinc-600 dark:text-zinc-300">
                <span className="relative flex h-2.5 w-2.5 shrink-0">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-blue-500"></span>
                </span>
                <span>Agent [{targetAgent || 'Chuyên biệt'}] đang thực thi tác vụ...</span>
              </div>
            ) : executorStatus === 'completed' ? (
              <div className="space-y-1.5 pt-0.5">
                {execSummary ? (
                  <div className="p-2.5 rounded bg-zinc-50 dark:bg-zinc-900/80 border border-zinc-200 dark:border-zinc-800/80 text-zinc-700 dark:text-zinc-300 max-h-36 overflow-y-auto whitespace-pre-wrap leading-relaxed">
                    {execSummary}
                  </div>
                ) : (
                  <div className="text-zinc-500 dark:text-zinc-400 italic">
                    Tác vụ đã được thực thi thành công bởi Agent [{targetAgent || 'Executor'}].
                  </div>
                )}
              </div>
            ) : (
              <div className="py-1 text-zinc-400 dark:text-zinc-600 italic">
                Chờ thực thi...
              </div>
            )}
          </div>

          {/* Mục 3: Verifier Node (Kiểm Định Chất Lượng & Zero-Hallucination) */}
          <div className="p-3.5 rounded-lg bg-white dark:bg-zinc-950/60 border border-zinc-200 dark:border-zinc-800 shadow-2xs space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-sans font-bold text-xs text-emerald-600 dark:text-emerald-400">
                <ShieldCheck className="w-4 h-4" />
                <span>Verifier Node (Kiểm Định Chất Lượng &amp; Zero-Hallucination)</span>
              </div>
              {verifierStatus === 'completed' && (
                isAuditPassed ? (
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" />
                    <span>Audit Passed (100% Verified)</span>
                  </span>
                ) : (
                  <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 flex items-center gap-1">
                    <RotateCcw className="w-3 h-3" />
                    <span>Retry Loop (Lần {retryCount || 1}/2)</span>
                  </span>
                )
              )}
            </div>

            {verifierStatus === 'active' ? (
              <div className="flex items-center gap-2.5 py-1.5 text-zinc-600 dark:text-zinc-300">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-emerald-500 shrink-0" />
                <span>Đang đối soát kết quả với kế hoạch ban đầu và kiểm định tính trung thực...</span>
              </div>
            ) : verifierStatus === 'completed' ? (
              <div className="space-y-1.5 pt-0.5">
                {verifierFeedback ? (
                  <div className="p-2.5 rounded bg-zinc-50 dark:bg-zinc-900/80 border border-zinc-200 dark:border-zinc-800/80 text-zinc-700 dark:text-zinc-300 whitespace-pre-wrap leading-relaxed">
                    <span className="font-semibold text-emerald-600 dark:text-emerald-400">Tiêu chí đối soát: </span>
                    {verifierFeedback}
                  </div>
                ) : (
                  <div className="text-zinc-500 dark:text-zinc-400 italic">
                    Kết quả đã được đối soát kỹ lưỡng, đảm bảo tính chuẩn xác và không ảo giác (Zero-Hallucination).
                  </div>
                )}
              </div>
            ) : (
              <div className="py-1 text-zinc-400 dark:text-zinc-600 italic">
                Chờ thực thi...
              </div>
            )}
          </div>

          {/* Error Banner */}
          {error && (
            <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-600 dark:text-red-400 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
