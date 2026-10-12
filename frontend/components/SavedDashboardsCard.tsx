'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { LayoutDashboard, Loader2, Pencil, RefreshCw, Share2, Trash2, X } from 'lucide-react';
import { DynamicDashboard } from './dashboard/DynamicDashboard';
import {
  deleteDashboard,
  listDashboards,
  openDashboard,
  patchDashboard,
  refreshDashboard,
  type OpenedDashboard,
  type SavedDashboard,
} from '../lib/dashboardsApi';
import { t, useLang } from '../lib/i18n';
import { toast } from '../lib/toast';

const iconButton =
  'rounded-md p-1.5 text-foreground-muted hover:bg-surface-raised hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary disabled:opacity-40';

/** The dashboards the user saved (`/dashboards` in the chat box) and the ones colleagues of the tenant shared: open, refresh, share, rename, delete. */
export const SavedDashboardsCard: React.FC = () => {
  const [lang] = useLang();
  const [items, setItems] = useState<SavedDashboard[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [opened, setOpened] = useState<OpenedDashboard | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await listDashboards());
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** Runs one action on one dashboard, with the busy mark and the failure toast every action shares. */
  const act = async (item: SavedDashboard, failKey: 'saved.openFailed' | 'saved.refreshFailed' | 'saved.actionFailed', run: () => Promise<void>) => {
    setBusyId(item.id);
    try {
      await run();
    } catch (e: unknown) {
      toast.error(t(lang, failKey, { error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusyId(null);
    }
  };

  const open = (item: SavedDashboard) => act(item, 'saved.openFailed', async () => setOpened(await openDashboard(item.id)));

  const refresh = (item: SavedDashboard) =>
    act(item, 'saved.refreshFailed', async () => {
      const fresh = await refreshDashboard(item.id);
      toast.success(t(lang, 'saved.refreshed', { title: item.title }));
      if (opened?.id === item.id) setOpened(fresh);
      await load();
    });

  const toggleShare = (item: SavedDashboard) => {
    if (!item.shared && !window.confirm(t(lang, 'saved.shareConfirm', { title: item.title }))) return Promise.resolve();
    return act(item, 'saved.actionFailed', async () => {
      await patchDashboard(item.id, { shared: !item.shared });
      await load();
    });
  };

  const rename = (item: SavedDashboard) => {
    const title = window.prompt(t(lang, 'saved.renamePrompt'), item.title)?.trim();
    if (!title || title === item.title) return Promise.resolve();
    return act(item, 'saved.actionFailed', async () => {
      await patchDashboard(item.id, { title });
      await load();
    });
  };

  const remove = (item: SavedDashboard) => {
    if (!window.confirm(t(lang, 'saved.confirmDelete', { title: item.title }))) return Promise.resolve();
    return act(item, 'saved.actionFailed', async () => {
      await deleteDashboard(item.id);
      if (opened?.id === item.id) setOpened(null);
      toast.success(t(lang, 'saved.deleted', { title: item.title }));
      await load();
    });
  };

  if (error) return <p role="alert" className="text-sm text-accent-error">{t(lang, 'saved.loadFailed', { error })}</p>;
  if (items === null) {
    return (
      <div className="flex items-center gap-2 text-sm text-foreground-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'saved.loading')}
      </div>
    );
  }
  if (items.length === 0) return <p className="text-sm text-foreground-secondary">{t(lang, 'saved.empty')}</p>;

  return (
    <section aria-label={t(lang, 'saved.title')} className="space-y-3" data-testid="saved-dashboards">
      <h3 className="text-sm font-bold text-foreground">{t(lang, 'saved.title')}</h3>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {items.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-xs hover:bg-surface-raised/50">
            <LayoutDashboard className="h-3.5 w-3.5 shrink-0 text-accent-primary" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium text-foreground" title={item.title}>{item.title}</p>
              <p className="truncate text-foreground-muted">
                {item.filename} · {t(lang, 'saved.colUpdated')} {new Date(item.updated_at).toLocaleString(lang === 'vi' ? 'vi-VN' : 'en-GB')}
                {!item.mine && ` · ${t(lang, 'saved.sharedWithYou')}`}
                {item.mine && item.shared && ` · ${t(lang, 'saved.sharedBadge')}`}
              </p>
            </div>
            <button type="button" onClick={() => void open(item)} disabled={busyId === item.id} className="btn-dash">
              {busyId === item.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
              {t(lang, 'saved.open')}
            </button>
            {item.mine && (
              <>
                <button type="button" onClick={() => void refresh(item)} disabled={busyId === item.id} title={t(lang, 'saved.refreshHint')} aria-label={t(lang, 'saved.refresh')} className={iconButton}>
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
                <button type="button" onClick={() => void toggleShare(item)} disabled={busyId === item.id} title={t(lang, item.shared ? 'saved.unshare' : 'saved.share')} aria-label={t(lang, item.shared ? 'saved.unshare' : 'saved.share')} aria-pressed={item.shared} className={`${iconButton} ${item.shared ? 'text-accent-primary' : ''}`}>
                  <Share2 className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
                <button type="button" onClick={() => void rename(item)} disabled={busyId === item.id} title={t(lang, 'saved.rename')} aria-label={t(lang, 'saved.rename')} className={iconButton}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
                <button type="button" onClick={() => void remove(item)} disabled={busyId === item.id} title={t(lang, 'saved.delete')} aria-label={t(lang, 'saved.delete')} className={`${iconButton} hover:!bg-accent-error/10 hover:!text-accent-error`}>
                  <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
      {opened && (
        <div className="space-y-2">
          <button type="button" onClick={() => setOpened(null)} className="btn-dash">
            <X className="h-3.5 w-3.5" aria-hidden="true" /> {t(lang, 'saved.close')}
          </button>
          <DynamicDashboard key={`${opened.id}-${opened.updated_at}`} spec={opened.spec} saveable={false} />
        </div>
      )}
    </section>
  );
};
