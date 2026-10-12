import { describe, expect, it } from 'vitest';
import { isFinished, jobIdOf } from '../../lib/codingApi';
import { MODE_AGENT_ID, agentModeAllowed } from '../../lib/agents';

describe('coding task helpers', () => {
  it('finds the task id in the chat reply that queued it', () => {
    const id = '0123456789abcdef0123456789abcdef';
    expect(jobIdOf(`Coding task received (id ${id}). The agent works in an isolated copy.`)).toBe(id);
    expect(jobIdOf('Đã nhận tác vụ lập trình (mã 0123456789abcdef0123456789abcdef).')).toBe(id);
    expect(jobIdOf('no id here, and 0123 is too short')).toBeNull();
    expect(jobIdOf('')).toBeNull();
  });

  it('polls until the task has finished or failed', () => {
    expect(['queued', 'running'].map((s) => isFinished(s as 'queued' | 'running'))).toEqual([false, false]);
    expect(isFinished('done')).toBe(true);
    expect(isFinished('failed')).toBe(true);
  });

  it('knows the coding mode, and a department policy can take it away', () => {
    expect(MODE_AGENT_ID['Coding Agent']).toBe('coding_agent');
    expect(agentModeAllowed(['rag_agent'], 'Coding Agent')).toBe(false);
    expect(agentModeAllowed(['coding_agent'], 'Coding Agent')).toBe(true);
    expect(agentModeAllowed(null, 'Coding Agent')).toBe(true);
  });
});
