/**
 * The Planner / Executor / Verifier timeline shown above an answer, as pure functions: each SSE event of the PEV loop
 * turns the previous `PEVTraceState` into the next one. Kept out of ChatInterface.tsx so the rules can be unit-tested.
 */

import type { StreamCallbacks } from './sse';
import type { PEVStepData, PEVTraceState } from './types';
import { getLang, t } from './i18n';

// The description of each node is written in the interface language. The step log / message the backend sends is not shown:
// its text is in one language, the user's language choice decides the text of the interface.

type Payload<K extends keyof StreamCallbacks> = Parameters<NonNullable<StreamCallbacks[K]>>[0];

export function createInitialPevTraceState(agentMode?: string): PEVTraceState {
  const isSearch = agentMode?.includes('Search');
  const isData = agentMode?.includes('Data');
  const isRag = agentMode?.includes('RAG');
  const targetAgent = isSearch ? 'search_agent' : isData ? 'data_agent' : isRag ? 'rag_agent' : undefined;

  return {
    currentStep: 'planner',
    planner: {
      status: 'active',
      title: 'Planner Node',
      description: t(getLang(), 'pev.planner.working'),
      targetAgent,
    },
    executor: {
      status: 'idle',
      title: 'Executor Node',
      description: t(getLang(), 'pev.waitPlanner'),
      agentName: targetAgent,
    },
    verifier: {
      status: 'idle',
      title: 'Verifier Node',
      description: t(getLang(), 'pev.waitExecutor'),
    },
  };
}

/** `pev_step` event: one node of the loop became active or finished. */
export function applyPevStep(state: PEVTraceState, step: PEVStepData): PEVTraceState {
  if (step.step === 'planner') {
    if (step.status === 'completed') {
      return { ...state, planner: { ...state.planner, status: 'completed', targetAgent: step.target || state.planner.targetAgent } };
    }
    return {
      ...state,
      currentStep: 'planner',
      planner: {
        ...state.planner,
        status: 'active',
        description: t(getLang(), 'pev.planner.working'),
      },
    };
  }
  if (step.step === 'executor') {
    if (step.status === 'completed') {
      return { ...state, executor: { ...state.executor, status: 'completed', agentName: step.target || state.executor.agentName } };
    }
    return {
      ...state,
      currentStep: 'executor',
      planner: { ...state.planner, status: 'completed', targetAgent: step.target || state.planner.targetAgent },
      executor: {
        ...state.executor,
        status: 'active',
        agentName: step.target || state.executor.agentName,
        description: t(getLang(), 'pev.executor.working', { agent: step.target || 'Executor' }),
      },
    };
  }
  if (step.step === 'verifier') {
    if (step.status === 'completed') {
      return { ...state, currentStep: 'completed', verifier: { ...state.verifier, status: 'completed', isVerified: true, auditPassed: true } };
    }
    return {
      ...state,
      currentStep: 'verifier',
      executor: { ...state.executor, status: 'completed' },
      verifier: {
        ...state.verifier,
        status: 'active',
        description: t(getLang(), 'pev.verifier.working'),
      },
    };
  }
  if (step.step === 'completed') {
    const verified = step.status === 'verified';
    return {
      ...state,
      currentStep: 'completed',
      planner: { ...state.planner, status: 'completed' },
      executor: { ...state.executor, status: 'completed' },
      verifier: { ...state.verifier, status: 'completed', isVerified: verified, auditPassed: verified, feedback: step.feedback || state.verifier.feedback },
    };
  }
  return state;
}

/** `plan` event: the Planner chose an agent. */
export function applyPlan(state: PEVTraceState, plan: Payload<'onPlan'>): PEVTraceState {
  return {
    ...state,
    currentStep: 'executor',
    planner: { ...state.planner, status: 'completed', plan: plan.plan, targetAgent: plan.target_agent, description: t(getLang(), 'pev.planner.done') },
    executor: {
      ...state.executor,
      status: 'active',
      agentName: plan.target_agent,
      description: t(getLang(), 'pev.executor.workingPlan', { agent: plan.target_agent }),
    },
  };
}

/** `executing` event: progress, or the finished result, of the chosen agent. */
export function applyExecuting(state: PEVTraceState, exec: Payload<'onExecuting'>): PEVTraceState {
  const targetAgent = exec.target_agent || state.executor.agentName;
  const completed = exec.status === 'completed' || Boolean(exec.execution_result);
  return {
    ...state,
    currentStep: completed ? 'verifier' : 'executor',
    executor: {
      ...state.executor,
      status: completed ? 'completed' : 'active',
      agentName: targetAgent,
      outputSummary: exec.execution_result || state.executor.outputSummary,
      description: completed
        ? t(getLang(), 'pev.executor.finished', { agent: targetAgent || 'Executor' })
        : t(getLang(), 'pev.executor.processing', { agent: targetAgent || 'Executor' }),
    },
    verifier: completed
      ? { ...state.verifier, status: 'active', description: t(getLang(), 'pev.verifier.working') }
      : state.verifier,
  };
}

/** `verifying` event: the Verifier accepted the answer or asked for a correction. */
export function applyVerifying(state: PEVTraceState, verifying: Payload<'onVerifying'>): PEVTraceState {
  const verified = verifying.is_verified;
  return {
    ...state,
    currentStep: verified ? 'completed' : 'verifier',
    verifier: {
      ...state.verifier,
      status: verified ? 'completed' : verifying.retry_count > 0 ? 'retry' : 'active',
      isVerified: verified,
      auditPassed: verified,
      feedback: verifying.verifier_feedback,
      retryCount: verifying.retry_count,
      description: verified
        ? t(getLang(), 'pev.verifier.success')
        : t(getLang(), 'pev.verifier.retrying', { count: verifying.retry_count }),
    },
  };
}

/** `final_response` event: everything is done, with the verdict. */
export function applyFinal(state: PEVTraceState, final: Payload<'onFinalResponse'>): PEVTraceState {
  return {
    ...state,
    currentStep: 'completed',
    planner: {
      ...state.planner,
      status: 'completed',
      targetAgent: final.target_agent || state.planner.targetAgent,
      plan: final.pev_trace?.planner?.plan_summary || state.planner.plan,
    },
    executor: {
      ...state.executor,
      status: 'completed',
      agentName: final.target_agent || state.executor.agentName,
      outputSummary: final.pev_trace?.executor?.execution_summary || state.executor.outputSummary,
    },
    verifier: {
      ...state.verifier,
      status: 'completed',
      isVerified: final.is_verified,
      auditPassed: final.is_verified,
      feedback: final.pev_trace?.verifier?.verifier_feedback || state.verifier.feedback,
    },
  };
}
