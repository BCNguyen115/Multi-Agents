'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, Trash2 } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { apiFetch } from '../../lib/apiFetch';
import { t, useLang } from '../../lib/i18n';
import { toast } from '../../lib/toast';
import { AdminDialog, ConfirmDialog } from '../admin/AdminDialog';

interface MemoryItem {
  id: string;
  memory: string;
  created_at: string;
}

/** "My memory": what the assistant remembers about the signed-in person, one item at a time or all at once. Nothing here is editable
 * text: an item that is wrong is deleted and, if it matters, said again. */
export function MemoryDialog() {
  const [lang] = useLang();
  const { memoryOpen, closeMemory } = useAuth();
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmAll, setConfirmAll] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      const response = await apiFetch('/api/memory');
      if (!response.ok) throw new Error(String(response.status));
      setItems(((await response.json()) as { items: MemoryItem[] }).items);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    if (memoryOpen) {
      setItems(null);
      void load();
    }
  }, [memoryOpen, load]);

  const forget = async (id?: string) => {
    setBusy(true);
    try {
      const response = await apiFetch(id ? `/api/memory/${encodeURIComponent(id)}` : '/api/memory', { method: 'DELETE' });
      if (!response.ok) throw new Error(String(response.status));
      toast.success(t(lang, 'memory.forgotten'));
      setConfirmAll(false);
      await load();
    } catch {
      toast.error(t(lang, 'memory.failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <AdminDialog open={memoryOpen && !confirmAll} title={t(lang, 'memory.title')} onClose={closeMemory}>
        <p className="text-sm text-foreground-secondary">{t(lang, 'memory.intro')}</p>
        {failed && <p role="alert" className="mt-3 text-sm text-accent-error">{t(lang, 'memory.failed')}</p>}
        {!failed && items === null && (
          <div className="mt-4 flex items-center gap-2 text-sm text-foreground-muted">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> {t(lang, 'memory.loading')}
          </div>
        )}
        {items && items.length === 0 && <p className="mt-4 text-sm text-foreground-secondary">{t(lang, 'memory.empty')}</p>}
        {items && items.length > 0 && (
          <>
            <ul className="mt-4 space-y-2" aria-label={t(lang, 'memory.title')}>
              {items.map((item) => (
                <li key={item.id} className="flex items-start gap-2 rounded-lg border border-border px-3 py-2">
                  <span className="min-w-0 flex-1 break-words text-sm text-foreground">{item.memory}</span>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void forget(item.id)}
                    aria-label={t(lang, 'memory.forgetOne', { text: item.memory.slice(0, 40) })}
                    className="flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full text-foreground-muted transition-colors hover:bg-surface-raised hover:text-accent-error focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary disabled:opacity-50"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
            <div className="mt-4 flex justify-end">
              <button type="button" className="btn-dash border-accent-error/50 text-accent-error" disabled={busy} onClick={() => setConfirmAll(true)}>
                {t(lang, 'memory.forgetAll')}
              </button>
            </div>
          </>
        )}
      </AdminDialog>
      <ConfirmDialog
        open={memoryOpen && confirmAll}
        title={t(lang, 'memory.forgetAll')}
        body={t(lang, 'memory.forgetAllBody')}
        confirmLabel={t(lang, 'memory.forgetAll')}
        danger
        busy={busy}
        onConfirm={() => void forget()}
        onCancel={() => setConfirmAll(false)}
      />
    </>
  );
}
