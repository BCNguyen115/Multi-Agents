'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { apiFetch } from '../lib/apiFetch';
import { isUnauthorized } from '../lib/authClient';
import { t, useLang } from '../lib/i18n';

interface PageViewerProps {
  /** `<category>/<file>.pdf`, the knowledge base key of the document. */
  docKey: string;
  fileName: string;
  page: number;
  /** The cited passage: the server shades it on the page. */
  snippet?: string;
  onClose: () => void;
}

/** One page of a stored PDF with the cited passage highlighted, in a dialog. */
export const PageViewer: React.FC<PageViewerProps> = ({ docKey, fileName, page, snippet, onClose }) => {
  const [lang] = useLang();
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [highlighted, setHighlighted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    const params = new URLSearchParams({ doc_key: docKey, page: String(page) });
    if (snippet) params.set('q', snippet.slice(0, 600));
    apiFetch(`/api/knowledge/page?${params.toString()}`)
      .then(async (response) => {
        if (isUnauthorized(response)) throw new Error(t(lang, 'session.expired'));
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setHighlighted(response.headers.get('x-highlighted') === '1');
        setImageUrl(objectUrl);
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [docKey, page, snippet, lang]);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const title = t(lang, 'source.pageTitle', { file: fileName, page });
  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-black/60 p-4"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div role="dialog" aria-modal="true" aria-label={title} className="flex max-h-full w-full max-w-3xl flex-col rounded-2xl border border-border bg-surface shadow-enterprise">
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-foreground">{title}</h2>
            {imageUrl && (
              <p className="text-xs text-foreground-muted" role="status">
                {highlighted ? t(lang, 'source.highlighted') : t(lang, 'source.notHighlighted')}
              </p>
            )}
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label={t(lang, 'source.close')}
            title={t(lang, 'source.close')}
            className="rounded-lg p-1.5 text-foreground-muted hover:bg-surface-raised hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="overflow-auto p-4">
          {error ? (
            <p role="alert" className="text-sm text-accent-error">{t(lang, 'source.pageFailed', { error })}</p>
          ) : imageUrl ? (
            // eslint-disable-next-line @next/next/no-img-element -- a blob URL of a server-rendered page, not a static asset
            <img src={imageUrl} alt={title} className="mx-auto h-auto max-w-full rounded-md border border-border bg-white" />
          ) : (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-foreground-muted">
              <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'source.pageLoading')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
