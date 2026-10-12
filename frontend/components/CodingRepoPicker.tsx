'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FolderGit2, GitBranch, Trash2, X } from 'lucide-react';
import { addRepo, discoverFolders, listRepos, removeRepo, selectedRepoId, selectRepo, type CodingRepo } from '../lib/codingApi';
import { t, useLang } from '../lib/i18n';
import { useDialogA11y } from '../lib/useDialogA11y';

type Folder = { path: string; name: string; branch: string };

/** Which repository the next Coding task is for, and where people add a GitHub link (anyone who may code) or pick a git folder the
 * server can see (administrators). The server checks both again for every task; this only keeps the choice in the browser. */
export function CodingRepoPicker() {
  const [lang] = useLang();
  const [repos, setRepos] = useState<CodingRepo[]>([]);
  const [canLocal, setCanLocal] = useState(false);
  const [chosen, setChosen] = useState('');
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<'github' | 'local'>('github');
  const [location, setLocation] = useState('');
  const [name, setName] = useState('');
  const [branch, setBranch] = useState('');
  const [folders, setFolders] = useState<Folder[]>([]);
  const [error, setError] = useState<string | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDialogA11y(open, dialog, close);

  const refresh = useCallback(async () => {
    try {
      const { repos: found, can_add_local } = await listRepos();
      setRepos(found);
      setCanLocal(can_add_local);
      const saved = selectedRepoId();
      const next = found.some((r) => r.id === saved) ? saved : found[0]?.id ?? '';
      setChosen(next);
      selectRepo(next);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!open || kind !== 'local' || !canLocal) return;
    discoverFolders().then((r) => setFolders(r.folders)).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [open, kind, canLocal]);

  const run = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      await refresh();
    } catch (e: unknown) {
      setError(t(lang, 'coding.repo.failed', { error: e instanceof Error ? e.message : String(e) }));
    }
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const created = await addRepo({ kind, location: location.trim(), name: name.trim(), branch: branch.trim() });
      selectRepo(created.id);
      setLocation('');
      setName('');
      setBranch('');
    });
  };

  const field = 'w-full rounded-lg border border-border bg-surface px-2 py-1.5 text-sm text-foreground';
  return (
    <div className="flex flex-wrap items-center gap-2 px-1 pb-2 text-sm" data-testid="coding-repo-picker">
      <label htmlFor="coding-repo" className="flex items-center gap-1.5 text-foreground-secondary">
        <FolderGit2 className="h-4 w-4" aria-hidden="true" /> {t(lang, 'coding.repo.label')}
      </label>
      <select
        id="coding-repo"
        value={chosen}
        onChange={(e) => { setChosen(e.target.value); selectRepo(e.target.value); }}
        disabled={repos.length === 0}
        className="max-w-[16rem] rounded-lg border border-border bg-surface px-2 py-1 text-sm text-foreground"
      >
        {repos.length === 0 && <option value="">{t(lang, 'coding.repo.none')}</option>}
        {repos.map((r) => (
          <option key={r.id} value={r.id}>{r.name} · {r.kind}{r.builtin ? ` (${t(lang, 'coding.repo.builtin')})` : ''}</option>
        ))}
      </select>
      <button type="button" className="btn-dash" onClick={() => setOpen(true)}>{t(lang, 'coding.repo.manage')}</button>
      {error && !open && <span role="alert" className="text-accent-error">{error}</span>}

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) close(); }}>
          <div ref={dialog} role="dialog" aria-modal="true" aria-label={t(lang, 'coding.repo.addTitle')} className="max-h-[90vh] w-full max-w-lg space-y-4 overflow-auto rounded-2xl border border-border bg-surface p-5 shadow-lg">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-foreground">{t(lang, 'coding.repo.addTitle')}</h2>
              <button type="button" onClick={close} aria-label={t(lang, 'coding.repo.close')} className="rounded p-1 text-foreground-muted hover:text-foreground"><X className="h-4 w-4" /></button>
            </div>

            <ul className="space-y-1">
              {repos.filter((r) => !r.builtin).map((r) => (
                <li key={r.id} className="flex items-center gap-2 text-sm text-foreground-secondary">
                  {r.kind === 'github' ? <GitBranch className="h-4 w-4 shrink-0" aria-hidden="true" /> : <FolderGit2 className="h-4 w-4 shrink-0" aria-hidden="true" />}
                  <span className="min-w-0 flex-1 truncate"><span className="font-medium text-foreground">{r.name}</span> <span className="font-mono text-xs">{r.location}</span></span>
                  {r.mine && (
                    <button type="button" aria-label={t(lang, 'coding.repo.remove', { name: r.name })} title={t(lang, 'coding.repo.remove', { name: r.name })} className="rounded p-1 text-foreground-muted hover:text-accent-error" onClick={() => void run(() => removeRepo(r.id))}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </li>
              ))}
            </ul>

            <form onSubmit={submit} className="space-y-3 border-t border-border pt-3">
              <div role="radiogroup" className="flex gap-4 text-sm text-foreground">
                <label className="flex items-center gap-1.5"><input type="radio" name="kind" checked={kind === 'github'} onChange={() => setKind('github')} /> {t(lang, 'coding.repo.github')}</label>
                <label className="flex items-center gap-1.5"><input type="radio" name="kind" checked={kind === 'local'} disabled={!canLocal} onChange={() => setKind('local')} /> {t(lang, 'coding.repo.local')}</label>
              </div>
              {!canLocal && <p className="text-xs text-foreground-muted">{t(lang, 'coding.repo.localAdminOnly')}</p>}

              {kind === 'github' ? (
                <input className={field} required value={location} onChange={(e) => setLocation(e.target.value)} placeholder={t(lang, 'coding.repo.url')} aria-label={t(lang, 'coding.repo.github')} inputMode="url" />
              ) : (
                <>
                  <select className={field} required value={location} aria-label={t(lang, 'coding.repo.pick')} onChange={(e) => {
                    setLocation(e.target.value);
                    const picked = folders.find((f) => f.path === e.target.value);
                    if (picked) { setName((n) => n || picked.name); setBranch((b) => b || picked.branch); }
                  }}>
                    <option value="">{t(lang, 'coding.repo.pick')}</option>
                    {folders.map((f) => <option key={f.path} value={f.path}>{f.name} — {f.path}</option>)}
                  </select>
                  {folders.length === 0 && <p className="text-xs text-foreground-muted">{t(lang, 'coding.repo.noFolders')}</p>}
                </>
              )}
              <input className={field} required maxLength={60} value={name} onChange={(e) => setName(e.target.value)} placeholder={t(lang, 'coding.repo.name')} aria-label={t(lang, 'coding.repo.name')} />
              <input className={field} maxLength={100} value={branch} onChange={(e) => setBranch(e.target.value)} placeholder={t(lang, 'coding.repo.branch')} aria-label={t(lang, 'coding.repo.branch')} />
              {error && <p role="alert" className="text-sm text-accent-error">{error}</p>}
              <button type="submit" className="btn-primary">{t(lang, 'coding.repo.add')}</button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
