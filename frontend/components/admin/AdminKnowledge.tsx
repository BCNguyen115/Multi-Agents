'use client';

import React, { useCallback, useMemo, useRef, useState } from 'react';
import { Loader2, Trash2, Upload } from 'lucide-react';
import { ConfirmDialog } from './AdminDialog';
import { AdminTable, type Column } from './AdminTable';
import { deleteKnowledge, listKnowledge, uploadKnowledge, type KnowledgeDocument } from '../../lib/adminApi';
import { formatTime } from '../../lib/adminConsole';
import { t, useLang } from '../../lib/i18n';
import { toast } from '../../lib/toast';
import { useAdminData } from '../../lib/useAdminData';

const ACCEPT = '.pdf,.docx,.pptx,.txt,.md';
const FIELD =
  'w-full max-w-xs rounded-md border border-border-input bg-surface px-2 py-1.5 text-base sm:text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary';

/** The documents the assistant answers from: add or replace one by uploading, remove one after a confirmation. */
export const AdminKnowledge: React.FC = () => {
  const [lang] = useLang();
  const fetcher = useCallback(() => listKnowledge(), []);
  const { data, error, reload } = useAdminData(fetcher);
  const [query, setQuery] = useState('');
  const [uploading, setUploading] = useState(false);
  const [doomed, setDoomed] = useState<KnowledgeDocument | null>(null);
  const [deleting, setDeleting] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (data ?? []).filter((d) => !needle || `${d.doc_key} ${d.category}`.toLowerCase().includes(needle));
  }, [data, query]);

  const upload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = ''; // the same file may be chosen again later
    if (!file) return;
    setUploading(true);
    try {
      const result = await uploadKnowledge(file);
      toast.success(t(lang, 'admin.knowledge.uploaded', { name: result.filename, chunks: result.chunks }));
      await reload();
    } catch (e: unknown) {
      toast.error(t(lang, 'admin.knowledge.uploadFailed', { error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setUploading(false);
    }
  };

  const remove = async () => {
    if (!doomed) return;
    setDeleting(true);
    try {
      const result = await deleteKnowledge(doomed.doc_key);
      toast.success(t(lang, 'admin.knowledge.deleted', { name: doomed.doc_key, chunks: result.deleted_chunks }));
      setDoomed(null);
      await reload();
    } catch (e: unknown) {
      toast.error(t(lang, 'admin.knowledge.deleteFailed', { name: doomed.doc_key, error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setDeleting(false);
    }
  };

  const columns: Column<KnowledgeDocument>[] = [
    { key: 'name', label: t(lang, 'admin.knowledge.colName'), cell: (d) => <span className="break-all font-medium text-foreground" title={d.doc_key}>{d.filename}</span> },
    { key: 'category', label: t(lang, 'admin.knowledge.colCategory'), cell: (d) => d.category, className: 'text-foreground-secondary' },
    { key: 'chunks', label: t(lang, 'admin.knowledge.colChunks'), cell: (d) => d.chunks.toLocaleString('en-US'), numeric: true },
    { key: 'pages', label: t(lang, 'admin.knowledge.colPages'), cell: (d) => (d.pages ? d.pages.toLocaleString('en-US') : '–'), numeric: true },
    { key: 'updated', label: t(lang, 'admin.knowledge.colUpdated'), cell: (d) => formatTime(d.updated_at, lang), className: 'whitespace-nowrap tabular-nums text-foreground-muted' },
    {
      key: 'actions',
      label: '',
      className: 'whitespace-nowrap text-right',
      cell: (d) => (
        <button type="button" className="btn-dash" onClick={() => setDoomed(d)} aria-label={`${t(lang, 'admin.knowledge.delete')} ${d.doc_key}`}>
          <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          {t(lang, 'admin.knowledge.delete')}
        </button>
      ),
    },
  ];

  return (
    <section aria-label={t(lang, 'admin.knowledge.title')} className="space-y-3" data-testid="admin-knowledge">
      <div className="flex flex-wrap items-center gap-3">
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t(lang, 'admin.knowledge.filter')} aria-label={t(lang, 'admin.knowledge.filter')} className={FIELD} />
        <input ref={fileInput} type="file" accept={ACCEPT} onChange={(e) => void upload(e)} className="sr-only" tabIndex={-1} aria-hidden="true" />
        <button type="button" className="btn-primary" onClick={() => fileInput.current?.click()} disabled={uploading}>
          {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Upload className="h-3.5 w-3.5" aria-hidden="true" />}
          {uploading ? t(lang, 'admin.knowledge.uploading') : t(lang, 'admin.knowledge.upload')}
        </button>
        <span className="text-xs text-foreground-muted">{t(lang, 'admin.knowledge.formats')}</span>
        {data && <span className="text-xs text-foreground-muted">{t(lang, 'admin.knowledge.count', { shown: shown.length, total: data.length })}</span>}
      </div>

      {error && <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.knowledge.loadFailed', { error })}</p>}
      {!data && !error && (
        <div className="flex items-center gap-2 text-sm text-foreground-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'admin.knowledge.loading')}
        </div>
      )}
      {data && <AdminTable columns={columns} rows={shown} rowKey={(d) => d.doc_key} empty={t(lang, 'admin.knowledge.empty')} label={t(lang, 'admin.knowledge.title')} />}

      <ConfirmDialog
        open={doomed !== null}
        title={t(lang, 'admin.knowledge.deleteTitle', { name: doomed?.filename ?? '' })}
        body={t(lang, 'admin.knowledge.deleteBody')}
        confirmLabel={t(lang, 'admin.knowledge.delete')}
        danger
        busy={deleting}
        onConfirm={() => void remove()}
        onCancel={() => setDoomed(null)}
      />
    </section>
  );
};
