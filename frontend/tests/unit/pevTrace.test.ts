import { describe, expect, it } from 'vitest';
import { applyExecuting, applyFinal, applyPevStep, applyPlan, applyVerifying, createInitialPevTraceState } from '../../lib/pevTrace';

describe('createInitialPevTraceState', () => {
  it('starts at the planner and pre-selects the agent the user picked', () => {
    const state = createInitialPevTraceState('RAG Agent');
    expect(state.currentStep).toBe('planner');
    expect(state.planner.status).toBe('active');
    expect(state.executor.status).toBe('idle');
    expect(state.planner.targetAgent).toBe('rag_agent');
    expect(createInitialPevTraceState('Data Agent').planner.targetAgent).toBe('data_agent');
    expect(createInitialPevTraceState('Search Agent').planner.targetAgent).toBe('search_agent');
    expect(createInitialPevTraceState('Auto').planner.targetAgent).toBeUndefined();
  });
});

describe('a whole PEV loop, event by event', () => {
  it('moves planner -> executor -> verifier -> completed and never mutates the previous state', () => {
    const initial = createInitialPevTraceState('RAG Agent');
    const frozen = JSON.stringify(initial);

    const planned = applyPlan(initial, { plan: 'Tra cứu NDA', target_agent: 'rag_agent' });
    expect(planned.currentStep).toBe('executor');
    expect(planned.planner).toMatchObject({ status: 'completed', plan: 'Tra cứu NDA', targetAgent: 'rag_agent' });
    expect(planned.executor.status).toBe('active');

    const running = applyExecuting(planned, { target_agent: 'rag_agent', status: 'fetching_data', message: 'đang truy vấn' });
    expect(running.currentStep).toBe('executor');
    expect(running.executor.description).toContain('rag_agent'); // the backend's message text is not shown
    expect(running.verifier.status).toBe('idle');

    const executed = applyExecuting(running, { target_agent: 'rag_agent', status: 'completed', execution_result: '{"answer":"2 năm"}' });
    expect(executed.currentStep).toBe('verifier');
    expect(executed.executor).toMatchObject({ status: 'completed', outputSummary: '{"answer":"2 năm"}' });
    expect(executed.verifier.status).toBe('active');

    const retry = applyVerifying(executed, { is_verified: false, verifier_feedback: 'thiếu trích dẫn', retry_count: 1 });
    expect(retry.verifier).toMatchObject({ status: 'retry', isVerified: false, retryCount: 1, feedback: 'thiếu trích dẫn' });
    expect(retry.currentStep).toBe('verifier');

    const verified = applyVerifying(retry, { is_verified: true, verifier_feedback: '', retry_count: 1 });
    expect(verified.currentStep).toBe('completed');
    expect(verified.verifier).toMatchObject({ status: 'completed', isVerified: true, auditPassed: true });

    expect(JSON.stringify(initial)).toBe(frozen);
  });

  it('a first verification failure is "active" (no retry yet), later ones are "retry"', () => {
    const state = createInitialPevTraceState();
    expect(applyVerifying(state, { is_verified: false, verifier_feedback: 'x', retry_count: 0 }).verifier.status).toBe('active');
    expect(applyVerifying(state, { is_verified: false, verifier_feedback: 'x', retry_count: 2 }).verifier.status).toBe('retry');
  });
});

describe('applyPevStep', () => {
  it('names the agent when a node starts, and the agent when it finishes', () => {
    const state = createInitialPevTraceState('RAG Agent');
    const started = applyPevStep(state, { step: 'executor', status: 'active', target: 'rag_agent', logs: 'chạy' });
    expect(started.planner.status).toBe('completed');
    expect(started.executor).toMatchObject({ status: 'active', agentName: 'rag_agent', description: expect.stringContaining('rag_agent') });
    const done = applyPevStep(started, { step: 'executor', status: 'completed', target: 'rag_agent' });
    expect(done.executor.status).toBe('completed');
  });

  it('the closing step carries the verdict, verified or with a warning', () => {
    const state = createInitialPevTraceState();
    expect(applyPevStep(state, { step: 'completed', status: 'verified' }).verifier).toMatchObject({ isVerified: true, auditPassed: true });
    const warned = applyPevStep(state, { step: 'completed', status: 'warning', feedback: 'chưa chắc' });
    expect(warned.verifier).toMatchObject({ isVerified: false, feedback: 'chưa chắc' });
  });

  it('ignores a step it does not know', () => {
    const state = createInitialPevTraceState();
    expect(applyPevStep(state, { step: 'mystery' as never, status: 'active' })).toBe(state);
  });
});

describe('applyFinal', () => {
  it('sets the verdict and prefers the trace summaries the server sent', () => {
    const state = applyFinal(createInitialPevTraceState('RAG Agent'), {
      response: '...',
      target_agent: 'rag_agent',
      is_verified: false,
      pev_trace: {
        status: 'Warning',
        planner: { node: 'Planner Node', target_agent: 'rag_agent', plan_summary: 'kế hoạch', status: 'completed' },
        executor: { node: 'Executor Node', agent_used: 'rag_agent', execution_summary: 'đã chạy', status: 'completed' },
        verifier: { node: 'Verifier Node', is_verified: false, verifier_feedback: 'cảnh báo', status: 'completed' },
      },
    });
    expect(state.currentStep).toBe('completed');
    expect(state.planner.plan).toBe('kế hoạch');
    expect(state.executor.outputSummary).toBe('đã chạy');
    expect(state.verifier).toMatchObject({ isVerified: false, auditPassed: false, feedback: 'cảnh báo' });
  });
});
