'use client';

import React, { useState } from 'react';
import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { apiFetch } from '../lib/apiFetch';
import { t, useLang, type MessageKey } from '../lib/i18n';
import type { SourceItem } from '../lib/types';

/** What a thumbs-down can say; the backend accepts exactly these. */
export const FEEDBACK_REASONS = ['wrong', 'outdated', 'missing_source', 'incomplete', 'off_topic', 'other'] as const;
type Reason = (typeof FEEDBACK_REASONS)[number];

interface FeedbackButtonsProps {
  messageId: string;
  /** The question this answer replied to. */
  query: string;
  sources: SourceItem[];
  /** Who answered (`rag_agent`...), the text of the answer, the PEV run, whether the Verifier passed it and how many times the agent answered again:
   * so a thumbs-down can be traced back to what produced it. */
  agent?: string;
  answer?: string;
  runId?: string;
  verified?: boolean;
  retries?: number;
}

const BUTTON =
  'inline-flex h-9 w-9 items-center justify-center rounded-full text-foreground-muted transition-colors cursor-pointer ' +
  'hover:bg-surface-raised hover:text-foreground disabled:opacity-60 disabled:cursor-default ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary';

const CHIP =
  'inline-flex min-h-8 items-center rounded-full border px-3 text-xs font-medium transition-colors cursor-pointer ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary';

/**
 * Thumbs up / down under a finished answer of any agent. A thumbs-down asks what was wrong (one tap on a reason, or skip). The backend keeps the
 * row with what the answer cited, who answered, the answer itself and the verdict (`rag_feedback`): the Quality page of the console reads them,
 * and `scripts/export_feedback_eval.py` turns them into an evaluation set made of the users' own questions.
 */
export function FeedbackButtons({ messageId, query, sources, agent = '', answer = '', runId = '', verified, retries = 0 }: FeedbackButtonsProps) {
  const [lang] = useLang();
  const [sent, setSent] = useState<'up' | 'down' | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const [reasons, setReasons] = useState<Reason[]>([]);

  const send = async (rating: 1 | -1, why: Reason[] = []) => {
    if (busy || sent) return;
    setBusy(true);
    setFailed(false);
    try {
      const response = await apiFetch('/api/chat/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rating,
          query,
          message_id: messageId,
          agent: agent.toLowerCase().replace(/[^a-z_]/g, '').slice(0, 40),
          answer: answer.slice(0, 4000),
          run_id: runId,
          verified: verified ?? null,
          retries,
          reasons: why,
          cited: sources.slice(0, 10).map((s) => ({
            file: s.file ?? '',
            section: s.section ?? '',
            page: s.page ?? null,
            snippet: (s.snippet ?? '').slice(0, 400),
          })),
        }),
      });
      if (!response.ok) throw new Error(String(response.status));
      setSent(rating === 1 ? 'up' : 'down');
      setChoosing(false);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2 pt-1" data-testid="feedback">
      <div className="flex items-center gap-1" role="group" aria-label={t(lang, 'feedback.label')}>
        <button
          type="button"
          className={`${BUTTON} ${sent === 'up' ? 'text-accent-primary' : ''}`}
          onClick={() => send(1)}
          disabled={busy || sent !== null}
          aria-pressed={sent === 'up'}
          aria-label={t(lang, 'feedback.up')}
          title={t(lang, 'feedback.up')}
        >
          <ThumbsUp className="h-4 w-4" aria-hidden="true" />
        </button>
        <button
          type="button"
          className={`${BUTTON} ${sent === 'down' || choosing ? 'text-accent-primary' : ''}`}
          onClick={() => setChoosing(true)}
          disabled={busy || sent !== null}
          aria-pressed={sent === 'down' || choosing}
          aria-expanded={choosing}
          aria-label={t(lang, 'feedback.down')}
          title={t(lang, 'feedback.down')}
        >
          <ThumbsDown className="h-4 w-4" aria-hidden="true" />
        </button>
        {sent && (
          <span role="status" className="ml-1 text-xs text-foreground-muted">
            {t(lang, 'feedback.thanks')}
          </span>
        )}
        {failed && (
          <span role="alert" className="ml-1 text-xs text-accent-error">
            {t(lang, 'feedback.failed')}
          </span>
        )}
      </div>
      {choosing && sent === null && (
        <fieldset className="space-y-2" data-testid="feedback-reasons">
          <legend className="text-xs font-semibold text-foreground-secondary">{t(lang, 'feedback.reasonsTitle')}</legend>
          <div className="flex flex-wrap gap-2">
            {FEEDBACK_REASONS.map((reason) => {
              const on = reasons.includes(reason);
              return (
                <button
                  key={reason}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setReasons(on ? reasons.filter((r) => r !== reason) : [...reasons, reason])}
                  className={`${CHIP} ${on ? 'border-accent-primary bg-accent-primary/10 text-accent-primary' : 'border-border-input text-foreground-secondary hover:bg-surface-raised'}`}
                >
                  {t(lang, `feedback.reason.${reason}` as MessageKey)}
                </button>
              );
            })}
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn-primary" disabled={busy} onClick={() => send(-1, reasons)}>
              {t(lang, 'feedback.submit')}
            </button>
            <button type="button" className="btn-dash" disabled={busy} onClick={() => send(-1, [])}>
              {t(lang, 'feedback.skip')}
            </button>
          </div>
        </fieldset>
      )}
    </div>
  );
}
