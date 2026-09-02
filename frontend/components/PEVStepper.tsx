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
import { PEVStepData, PEVTrace } from '../lib/types';

interface PEVStepperProps {
  pevStep?: PEVStepData;
  pevEvents?: {
    plan?: { plan: string; target_agent: string };
    executing?: { target_agent: string; execution_result: string };
    verifying?: { is_verified: boolean; verifier_feedback: string; retry_count: number };
    final_response?: { response: string; target_agent: string; is_verified: boolean };
    error?: string;
  };
  pevTrace?: PEVTrace;
  isStreaming?: boolean;
}

export const PEVStepper: React.FC<PEVStepperProps> = ({
  pevStep,
  pevEvents,
  pevTrace,
  isStreaming,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!pevStep && !pevEvents && !pevTrace && !isStreaming) return null;

  const currentStep = pevStep?.step || (
    pevTrace || pevEvents?.verifying
      ? 'completed'
      : pevEvents?.executing
      ? 'verifier'
      : pevEvents?.plan
      ? 'executor'
      : 'planner'
  );

  const plan = pevEvents?.plan || (pevTrace?.planner ? { plan: pevTrace.planner.plan_summary || 'Lập kế hoạch phân tích', target_agent: pevTrace.planner.target_agent || 'data_agent' } : undefined);
  const executing = pevEvents?.executing || (pevTrace?.executor ? { target_agent: pevTrace.executor.agent_used || 'data_agent', execution_result: pevTrace.executor.execution_summary || 'Thực thi mã thành công' } : undefined);
  const verifying = pevEvents?.verifying || (pevTrace?.verifier ? { is_verified: pevTrace.verifier.is_verified ?? true, verifier_feedback: pevTrace.verifier.verifier_feedback || 'Đã kiểm duyệt', retry_count: 0 } : undefined);
  const error = pevEvents?.error;

  const isPlannerDone = Boolean(plan) || Boolean(pevTrace) || currentStep === 'executor' || currentStep === 'verifier' || currentStep === 'completed';
  const isExecutorDone = Boolean(executing) || Boolean(pevTrace) || currentStep === 'verifier' || currentStep === 'completed';
  const isVerifierDone = (Boolean(verifying) && (verifying?.is_verified ?? true)) || Boolean(pevTrace) || currentStep === 'completed';

  const isPlannerActive = isStreaming && currentStep === 'planner';
  const isExecutorActive = isStreaming && currentStep === 'executor';
  const isVerifierActive = isStreaming && currentStep === 'verifier';

  const isVerified =
    pevEvents?.verifying?.is_verified ??
    pevEvents?.final_response?.is_verified ??
    (pevTrace?.status ? pevTrace.status === 'Verified' : undefined) ??
    pevTrace?.verifier?.is_verified ??
    true;

  let statusText = 'Khởi tạo luồng PEV Loop...';
  if (pevStep?.logs) {
    statusText = pevStep.logs;
  } else if (isStreaming) {
    if (isPlannerActive) statusText = 'Agent đang phân tích yêu cầu & lập kế hoạch...';
    else if (isExecutorActive) statusText = `Planner hoàn tất ➔ Executor [${plan?.target_agent || pevStep?.target || 'Agent'}] đang thực thi...`;
    else if (isVerifierActive) statusText = 'Executor hoàn tất ➔ Verifier đang kiểm duyệt phản hồi...';
  } else {
    statusText = isVerified
      ? 'Chu trình suy luận PEV Loop hoàn tất (Verified)'
      : 'Chu trình suy luận PEV Loop hoàn tất (⚠️ Unverified - Cần kiểm duyệt lại)';
  }

  return (
    <div className="my-3 border border-slate-200/90 dark:border-slate-800 rounded-2xl bg-white dark:bg-slate-900 shadow-xs overflow-hidden text-xs transition-colors duration-300">
      {/* Header bar */}
      <div
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center justify-between px-4 py-2.5 bg-slate-50 dark:bg-slate-800/80 hover:bg-slate-100/80 dark:hover:bg-slate-800 cursor-pointer transition-colors duration-200 ease-out border-b border-slate-200/80 dark:border-slate-700/80"
      >
        <div className="flex items-center space-x-2.5 overflow-hidden">
          <Brain className={`w-4 h-4 shrink-0 text-[#005697] dark:text-blue-400 ${isStreaming ? 'animate-pulse' : ''}`} />
          <span className="font-extrabold text-[#005697] dark:text-blue-300 shrink-0">
            PEV Loop Stepper: Core Reasoning Workflow
          </span>
          <span className="text-slate-500 dark:text-slate-400 font-medium italic truncate">{statusText}</span>
        </div>

        <div className="flex items-center space-x-2 shrink-0">
          {isStreaming ? (
            <span className="flex items-center space-x-1 bg-amber-50 dark:bg-amber-950/60 text-[#F37021] dark:text-amber-400 border border-amber-200 dark:border-amber-800 px-2.5 py-0.5 rounded-full font-bold text-[10px] animate-pulse">
              <Loader2 className="w-3 h-3 animate-spin text-[#F37021] dark:text-amber-400" />
              <span>Real-time Active</span>
            </span>
          ) : isVerified ? (
            <span className="flex items-center space-x-1 bg-emerald-50 dark:bg-emerald-950/60 text-[#10B981] dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 px-2.5 py-0.5 rounded-full font-bold text-[10px]">
              <CheckCircle2 className="w-3 h-3 text-[#10B981] dark:text-emerald-400" />
              <span>(Verified)</span>
            </span>
          ) : (
            <span className="flex items-center space-x-1 bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800 px-2.5 py-0.5 rounded-full font-bold text-[10px]">
              <AlertCircle className="w-3 h-3 text-amber-600 dark:text-amber-400" />
              <span>⚠️ Unverified</span>
            </span>
          )}
          <button className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors duration-200 ease-out">
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Timeline Nodes Bar */}
      <div className="p-3.5 bg-white dark:bg-slate-900 flex items-center justify-around border-b border-slate-100 dark:border-slate-800 gap-2">
        {/* Step 1: Planner Node */}
        <div className="flex items-center space-x-2">
          <div
            className={`w-7 h-7 rounded-full flex items-center justify-center font-bold transition-all duration-200 ease-out ${
              isPlannerDone
                ? 'bg-[#F37021] text-white shadow-xs'
                : isPlannerActive
                ? 'bg-amber-50 dark:bg-amber-950/60 text-[#F37021] dark:text-amber-400 ring-2 ring-[#F37021] animate-pulse'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-500 border border-slate-200 dark:border-slate-700'
            }`}
          >
            {isPlannerActive ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-[#F37021]" />
            ) : isPlannerDone ? (
              <CheckCircle2 className="w-3.5 h-3.5 text-white" />
            ) : (
              <Compass className="w-3.5 h-3.5 text-slate-400" />
            )}
          </div>
          <div>
            <div className="font-bold text-[#212529] dark:text-slate-200 flex items-center gap-1">
              1. Planner Node
            </div>
            <div className="text-[10px] text-[#495057] dark:text-slate-400">
              {plan?.target_agent ? `Target: ${plan.target_agent}` : isPlannerActive ? 'Đang lập kế hoạch' : 'Lập kế hoạch'}
            </div>
          </div>
        </div>

        <div className={`h-0.5 flex-1 max-w-[40px] transition-colors duration-200 ease-out ${isPlannerDone ? 'bg-[#F37021]' : 'bg-slate-200 dark:bg-slate-800'}`} />

        {/* Step 2: Executor Node */}
        <div className="flex items-center space-x-2">
          <div
            className={`w-7 h-7 rounded-full flex items-center justify-center font-bold transition-all duration-200 ease-out ${
              isExecutorDone
                ? 'bg-[#005697] text-white shadow-xs'
                : isExecutorActive
                ? 'bg-blue-50 dark:bg-blue-950/60 text-[#005697] dark:text-blue-400 ring-2 ring-[#005697] animate-pulse'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-500 border border-slate-200 dark:border-slate-700'
            }`}
          >
            {isExecutorActive ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-[#005697]" />
            ) : isExecutorDone ? (
              <CheckCircle2 className="w-3.5 h-3.5 text-white" />
            ) : (
              <Cpu className="w-3.5 h-3.5 text-slate-400" />
            )}
          </div>
          <div>
            <div className="font-bold text-[#212529] dark:text-slate-200 flex items-center gap-1">
              2. Executor Node
            </div>
            <div className="text-[10px] text-[#495057] dark:text-slate-400">
              {executing?.target_agent || plan?.target_agent || (isExecutorActive ? 'Đang thực thi' : 'Chờ thực thi')}
            </div>
          </div>
        </div>

        <div className={`h-0.5 flex-1 max-w-[40px] transition-colors duration-200 ease-out ${isExecutorDone ? 'bg-[#005697]' : 'bg-slate-200 dark:bg-slate-800'}`} />

        {/* Step 3: Verifier Node */}
        <div className="flex items-center space-x-2">
          <div
            className={`w-7 h-7 rounded-full flex items-center justify-center font-bold transition-all duration-200 ease-out ${
              isVerifierActive
                ? 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 ring-2 ring-emerald-500 animate-pulse'
                : isVerifierDone
                ? isVerified
                  ? 'bg-emerald-600 text-white shadow-xs'
                  : 'bg-amber-500 text-white shadow-xs'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-500 border border-slate-200 dark:border-slate-700'
            }`}
          >
            {isVerifierActive ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-emerald-600" />
            ) : isVerifierDone ? (
              isVerified ? (
                <CheckCircle2 className="w-3.5 h-3.5 text-white" />
              ) : (
                <AlertCircle className="w-3.5 h-3.5 text-white" />
              )
            ) : (
              <ShieldCheck className="w-3.5 h-3.5 text-slate-400" />
            )}
          </div>
          <div>
            <div className="font-bold text-[#212529] dark:text-slate-200 flex items-center gap-1">
              3. Verifier Node
            </div>
            <div className="text-[10px] text-[#495057] dark:text-slate-400">
              {isVerifierDone ? (isVerified ? 'Xác minh 100%' : 'Cảnh báo Unverified') : isVerifierActive ? 'Đang kiểm duyệt' : 'Chờ kiểm duyệt'}
            </div>
          </div>
        </div>
      </div>

      {/* Detailed Log Accordion Panel */}
      {isExpanded && (
        <div className="p-4 bg-slate-50/80 dark:bg-slate-800/60 space-y-3 font-mono text-[11px] leading-relaxed animate-in fade-in duration-300 ease-in-out">
          {plan && (
            <div className="p-2.5 bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-700/80 rounded-xl space-y-1">
              <div className="font-bold text-[#F37021] flex items-center gap-1.5">
                <Compass className="w-3.5 h-3.5" /> [Planner Step Output]
              </div>
              <p className="text-slate-700 dark:text-slate-300 whitespace-pre-wrap">{plan.plan}</p>
              <div className="text-[10px] text-slate-500 dark:text-slate-400 font-semibold">
                ➜ Target Agent Assigned: <span className="text-[#005697] dark:text-blue-400">{plan.target_agent}</span>
              </div>
            </div>
          )}

          {executing && (
            <div className="p-2.5 bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-700/80 rounded-xl space-y-1">
              <div className="font-bold text-[#005697] dark:text-blue-400 flex items-center gap-1.5">
                <Cpu className="w-3.5 h-3.5" /> [Executor Execution Result]
              </div>
              <div className="text-slate-700 dark:text-slate-300 max-h-36 overflow-y-auto whitespace-pre-wrap bg-slate-50 dark:bg-slate-800 p-2 rounded border border-slate-100 dark:border-slate-700">
                {executing.execution_result}
              </div>
            </div>
          )}

          {verifying && (
            <div className="p-2.5 bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-700/80 rounded-xl space-y-1">
              <div className="font-bold text-emerald-600 dark:text-emerald-400 flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5" /> [Verifier Inspection Report]
              </div>
              <div className="text-slate-700 dark:text-slate-300">
                Status: <span className="font-bold text-emerald-600 dark:text-emerald-400">{verifying.is_verified ? 'VERIFIED PASSED' : 'REJECTED RE-RUN'}</span>
              </div>
              {verifying.verifier_feedback && (
                <div className="text-slate-600 dark:text-slate-400 italic">
                  Feedback: "{verifying.verifier_feedback}"
                </div>
              )}
            </div>
          )}

          {error && (
            <div className="p-2.5 bg-rose-50 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-800 rounded-xl text-rose-700 dark:text-rose-300 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
