'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { FileText, Loader2, Trash2 } from 'lucide-react';
import { apiFetch } from '../lib/apiFetch';
import { isUnauthorized } from '../lib/authClient';
import { t, useLang } from '../lib/i18n';
import { toast } from '../lib/toast';

export interface KnowledgeDoc {
  doc_key: string;
  filename: string;
  category: string;
  chunks: number;
  pages: number | null;
  updated_at: string | null;
  has_pdf: boolean;
}

/** The documents stored in the knowledge base (`/docs` in the chat box), with a delete button per document. */
export const KnowledgeDocumentsCard: React.FC = () => {
  const [lang] = useLang();
  const [documents, setDocuments] = useState<KnowledgeDoc[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await apiFetch('/api/knowledge/documents');
      if (isUnauthorized(response)) throw new Error(t(lang, 'session.expired'));
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${response.status}`);
      setDocuments(body as KnowledgeDoc[]);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [lang]);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = async (doc: KnowledgeDoc) => {
    if (!window.confirm(t(lang, 'docs.confirmDelete', { name: doc.filename }))) return;
    setBusyKey(doc.doc_key);
    try {
      const response = await apiFetch(`/api/knowledge/documents?doc_key=${encodeURIComponent(doc.doc_key)}`, { method: 'DELETE' });
      if (isUnauthorized(response)) throw new Error(t(lang, 'session.expired'));
      const body = await response.json().catch(() => ({}));
      if (response.status === 403) throw new Error(t(lang, 'docs.noPermission'));
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${response.status}`);
      toast.success(t(lang, 'docs.deleted', { name: doc.filename, chunks: body.deleted_chunks ?? doc.chunks }), { title: 'Knowledge base' });
      await load();
    } catch (e: unknown) {
      toast.error(t(lang, 'docs.deleteFailed', { name: doc.filename, error: e instanceof Error ? e.message : String(e) }), { title: 'Knowledge base' });
    } finally {
      setBusyKey(null);
    }
  };

  if (error) return <p role="alert" className="text-sm text-accent-error">{t(lang, 'docs.loadFailed', { error })}</p>;
  if (documents === null) {
    return (
      <div className="flex items-center gap-2 text-sm text-foreground-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'docs.loading')}
      </div>
    );
  }
  if (documents.length === 0) return <p className="text-sm text-foreground-secondary">{t(lang, 'docs.empty')}</p>;

  const totalChunks = documents.reduce((sum, d) => sum + d.chunks, 0);
  return (
    <section aria-label={t(lang, 'docs.title')} className="space-y-3" data-testid="knowledge-documents">
      <header>
        <h3 className="text-sm font-bold text-foreground">{t(lang, 'docs.title')}</h3>
        <p className="text-xs text-foreground-muted">{t(lang, 'docs.summary', { documents: documents.length, chunks: totalChunks })}</p>
      </header>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-raised text-foreground-muted">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'docs.colName')}</th>
              <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'docs.colCategory')}</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">{t(lang, 'docs.colChunks')}</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">{t(lang, 'docs.colPages')}</th>
              <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'docs.colUpdated')}</th>
              <th scope="col" className="px-3 py-2"><span className="sr-only">{t(lang, 'docs.delete')}</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {documents.map((doc) => (
              <tr key={doc.doc_key} className="hover:bg-surface-raised/50">
                <td className="max-w-xs px-3 py-2 font-medium text-foreground">
                  <span className="flex items-center gap-1.5 truncate" title={doc.doc_key}>
                    <FileText className="h-3.5 w-3.5 shrink-0 text-accent-primary" aria-hidden="true" />
                    {doc.filename}
                  </span>
                </td>
                <td className="px-3 py-2 uppercase tracking-wide text-foreground-secondary">{doc.category}</td>
                <td className="px-3 py-2 text-right tabular-nums">{doc.chunks}</td>
                <td className="px-3 py-2 text-right tabular-nums">{doc.pages ?? '–'}</td>
                <td className="whitespace-nowrap px-3 py-2 text-foreground-muted">
                  {doc.updated_at ? new Date(doc.updated_at).toLocaleString(lang === 'vi' ? 'vi-VN' : 'en-GB') : '–'}
                </td>
                <td className="px-3 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => void remove(doc)}
                    disabled={busyKey === doc.doc_key}
                    aria-label={t(lang, 'docs.deleteLabel', { name: doc.filename })}
                    title={t(lang, 'docs.delete')}
                    className="rounded-md p-1.5 text-foreground-muted hover:bg-accent-error/10 hover:text-accent-error focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-error/40 disabled:opacity-40"
                  >
                    {busyKey === doc.doc_key ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-foreground-muted">{t(lang, 'docs.replaceHint')}</p>
    </section>
  );
};
