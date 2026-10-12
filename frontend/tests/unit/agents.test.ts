import { describe, expect, it } from 'vitest';
import { agentModeAllowed, firstAllowedMode } from '../../lib/agents';

describe('agentModeAllowed', () => {
  it('allows everything when the policy says nothing', () => {
    expect(agentModeAllowed(null, 'Data Agent')).toBe(true);
    expect(agentModeAllowed(undefined, 'Database Agent')).toBe(true);
  });

  it('allows only the agents the policy lists, by the chat box\'s mode names', () => {
    const allowed = ['rag_agent', 'search_agent'];
    expect(agentModeAllowed(allowed, 'RAG Agent')).toBe(true);
    expect(agentModeAllowed(allowed, 'Search Agent')).toBe(true);
    expect(agentModeAllowed(allowed, 'Data Agent')).toBe(false);
    expect(agentModeAllowed(allowed, 'Database Agent')).toBe(false);
  });

  it('does not block a mode it does not know', () => {
    expect(agentModeAllowed(['rag_agent'], 'Some Future Agent')).toBe(true);
  });
});

describe('firstAllowedMode', () => {
  it('picks the first allowed mode in the chat box\'s order, or keeps the fallback when none is allowed', () => {
    expect(firstAllowedMode(['search_agent', 'data_agent'], 'RAG Agent')).toBe('Data Agent');
    expect(firstAllowedMode(['integration_agent'], 'RAG Agent')).toBe('RAG Agent');
    expect(firstAllowedMode(null, 'Search Agent')).toBe('RAG Agent');
  });
});
