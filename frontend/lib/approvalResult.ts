/** What `GET /api/chat/approve/{id}/result` answers, for the person who asked (two-person approval). */
export interface ApprovalOutcome {
  state: 'pending' | 'done';
  result?: { status?: string; response?: string; message?: string; data?: unknown };
}

/** The decision to show on the card and the text under it, or `null` while nobody has decided yet. */
export function describeOutcome(outcome: ApprovalOutcome): { decision: 'approved' | 'rejected'; text: string } | null {
  if (outcome.state !== 'done') return null;
  const result = outcome.result ?? {};
  // Only a successful execution is "approved and run"; a rejection and a failed execution both end the card, the text says which
  return { decision: result.status === 'success' ? 'approved' : 'rejected', text: result.response || result.message || '' };
}
