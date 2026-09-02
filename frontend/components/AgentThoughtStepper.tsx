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
  const [isExpanded, setIsExpanded] = useState(false);

  if (!pevEvents && !isStreaming) return null;

  const plan = pevEvents?.plan;
  const executing = pevEvents?.executing;
  const verifying = pevEvents?.verifying;
  const error = pevEvents?.error;

  const hasPlan = Boolean(plan);
  const hasExecuting = Boolean(executing);
  const hasVerifying = Boolean(verifying);

  let currentStatusText = 'Khởi tạo luồng tư duy PEV Loop...';
  if (isStreaming) {
    if (!hasPlan) currentStatusText = 'Agent đang lập kế hoạch suy luận...';
    else if (!hasExecuting) currentStatusText = `Planner giải quyết ➔ Đang chuyển giao tới [${plan?.target_agent || 'Executor'}]...`;
    else if (!hasVerifying) currentStatusText = 'Executor hoàn tất ➔ Verifier đang kiểm duyệt phản hồi...';
  } else {
    currentStatusText = 'Chu trình suy luận PEV Loop hoàn tất';
  }

  return (
    <div className="my-3 border border-slate-200 rounded-xl bg-slate-50/80 shadow-sm overflow-hidden text-xs">
      {/* Header bar */}
      <div
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center justify-between px-4 py-2.5 bg-slate-100/90 hover:bg-slate-200/70 cursor-pointer transition-colors border-b border-slate-200"
      >
        <div className="flex items-center space-x-2.5">
          <Brain className="w-4 h-4 text-brand-600 animate-pulse" />
          <span className="font-semibold text-slate-800 flex items-center gap-1.5">
            PEV Loop Stepper:
          </span>
          <span className="text-slate-600 font-medium italic">{currentStatusText}</span>
        </div>

        <div className="flex items-center space-x-2">
          {isStreaming ? (
            <span className="flex items-center space-x-1 bg-brand-100 text-brand-700 px-2 py-0.5 rounded-full font-medium text-[11px] animate-pulse">
              <Loader2 className="w-3 h-3 animate-spin" />
              <span>Streaming Thought</span>
            </span>
          ) : (
            <span className="flex items-center space-x-1 bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full font-medium text-[11px]">
              <CheckCircle2 className="w-3 h-3" />
              <span>Verified</span>
            </span>
          )}
          <button className="text-slate-500 hover:text-slate-800">
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Timeline Nodes Bar */}
      <div className="p-3.5 bg-white flex items-center justify-around border-b border-slate-100 gap-2">
        {/* Step 1: Planner */}
        <div className="flex items-center space-x-2">
          <div
            className={`w-7 h-7 rounded-full flex items-center justify-center font-bold ${
              hasPlan
                ? 'bg-brand-700 text-white shadow-sm'
                : isStreaming
                ? 'bg-brand-100 text-brand-700 animate-pulse'
                : 'bg-slate-200 text-slate-500'
            }`}
          >
            <Compass className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="font-semibold text-slate-800">1. Planner Node</div>
            <div className="text-[10px] text-slate-500">
              {plan?.target_agent ? `Target: ${plan.target_agent}` : 'Tạo kế hoạch'}
            </div>
          </div>
        </div>

        <div className="h-0.5 flex-1 bg-slate-200 max-w-[40px]" />

        {/* Step 2: Executor */}
        <div className="flex items-center space-x-2">
          <div
            className={`w-7 h-7 rounded-full flex items-center justify-center font-bold ${
              hasExecuting
                ? 'bg-indigo-600 text-white shadow-sm'
                : isStreaming && hasPlan
                ? 'bg-indigo-100 text-indigo-700 animate-pulse'
                : 'bg-slate-200 text-slate-500'
            }`}
          >
            <Cpu className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="font-semibold text-slate-800">2. Executor Node</div>
            <div className="text-[10px] text-slate-500">
              {executing?.target_agent || 'Thực thi Agent'}
            </div>
          </div>
        </div>

        <div className="h-0.5 flex-1 bg-slate-200 max-w-[40px]" />

        {/* Step 3: Verifier */}
        <div className="flex items-center space-x-2">
          <div
            className={`w-7 h-7 rounded-full flex items-center justify-center font-bold ${
              hasVerifying
                ? verifying?.is_verified
                  ? 'bg-emerald-600 text-white shadow-sm'
                  : 'bg-amber-600 text-white shadow-sm'
                : isStreaming && hasExecuting
                ? 'bg-emerald-100 text-emerald-700 animate-pulse'
                : 'bg-slate-200 text-slate-500'
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="font-semibold text-slate-800">3. Verifier Node</div>
            <div className="text-[10px] text-slate-500">
              {verifying ? (verifying.is_verified ? 'Verified ✅' : 'Feedback Loop 🔄') : 'Kiểm duyệt'}
            </div>
          </div>
        </div>
      </div>

      {/* Expandable Thought Detail Section */}
      {isExpanded && (
        <div className="p-4 space-y-3 bg-slate-50 border-t border-slate-200 font-mono text-[11px] text-slate-700">
          {plan && (
            <div className="bg-white p-3 rounded-lg border border-slate-200 shadow-2xs">
              <div className="font-bold text-brand-700 mb-1 flex items-center gap-1.5 font-sans text-xs">
                <Compass className="w-3.5 h-3.5" /> 📌 Kế Hoạch từ Planner Node:
              </div>
              <p className="whitespace-pre-wrap">{plan.plan}</p>
            </div>
          )}

          {executing && (
            <div className="bg-white p-3 rounded-lg border border-slate-200 shadow-2xs">
              <div className="font-bold text-indigo-700 mb-1 flex items-center gap-1.5 font-sans text-xs">
                <Cpu className="w-3.5 h-3.5" /> ⚡ Nhật Ký Thực Thi từ [{executing.target_agent}]:
              </div>
              <p className="whitespace-pre-wrap max-h-40 overflow-y-auto">{executing.execution_result.slice(0, 500)}...</p>
            </div>
          )}

          {verifying && (
            <div className="bg-white p-3 rounded-lg border border-slate-200 shadow-2xs">
              <div className="font-bold text-emerald-700 mb-1 flex items-center gap-1.5 font-sans text-xs">
                <ShieldCheck className="w-3.5 h-3.5" /> 🛡️ Đánh Giá từ Verifier Node:
              </div>
              <p className="whitespace-pre-wrap">
                Chất lượng: <span className={verifying.is_verified ? 'text-emerald-600 font-bold' : 'text-amber-600 font-bold'}>
                  {verifying.is_verified ? 'Đạt Tiêu Chuẩn (Passed)' : 'Cần Chỉnh Sửa'}
                </span>
                {verifying.verifier_feedback && ` | Feedback: ${verifying.verifier_feedback}`}
              </p>
            </div>
          )}

          {error && (
            <div className="bg-rose-50 p-3 rounded-lg border border-rose-200 text-rose-700 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
