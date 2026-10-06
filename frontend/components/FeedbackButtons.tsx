'use client';

import React, { useState } from 'react';
import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { apiFetch } from '../lib/apiFetch';
import { t, useLang } from '../lib/i18n';
import type { SourceItem } from '../lib/types';

interface FeedbackButtonsProps {
  messageId: string;
  /** The question this answer replied to. */
  query: string;
  sources: SourceItem[];
}

const BUTTON =
  'inline-flex h-9 w-9 items-center justify-center rounded-full text-foreground-muted transition-colors cursor-pointer ' +
  'hover:bg-surface-raised hover:text-foreground disabled:opacity-60 disabled:cursor-default ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40';

/**
 * Thumbs up / down under an answer that cites documents. The backend keeps them with what the answer cited (`rag_feedback`):
 * the seed of an evaluation set made of the users' own questions (scripts/export_feedback_eval.py).
 */
export function FeedbackButtons({ messageId, query, sources }: FeedbackButtonsProps) {
  const [lang] = useLang();
  const [sent, setSent] = useState<'up' | 'down' | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const send = async (rating: 1 | -1) => {
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
          cited: sources.slice(0, 10).map((s) => ({
            file: s.file,
            section: s.section ?? '',
            page: s.page ?? null,
            snippet: (s.snippet ?? '').slice(0, 400),
          })),
        }),
      });
      if (!response.ok) throw new Error(String(response.status));
      setSent(rating === 1 ? 'up' : 'down');
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-1 pt-1" role="group" aria-label={t(lang, 'feedback.label')} data-testid="feedback">
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
        className={`${BUTTON} ${sent === 'down' ? 'text-accent-primary' : ''}`}
        onClick={() => send(-1)}
        disabled={busy || sent !== null}
        aria-pressed={sent === 'down'}
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
  );
}
