'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { KeyRound, Loader2, Lock, LockOpen, LogOut, Plus } from 'lucide-react';
import { AdminDialog, ConfirmDialog } from './AdminDialog';
import { CreateAccountDialog } from './AdminCreateAccount';
import { CredentialsDialog } from './AdminCredentials';
import { ScopePicker } from './ScopePicker';
import {
  AdminError, bulkUsers, diffUser, getOrg, listAdminUsers, resetCredentials, signOutUser, updateAdminUser,
  type AdminDirectory, type AdminUser, type BulkActionName, type IssuedCredentials, type OrgTenant, type UserChanges,
} from '../../lib/adminApi';
import { onOrgChange } from '../../lib/adminEvents';
import { t, useLang, type MessageKey } from '../../lib/i18n';
import { toast } from '../../lib/toast';

type Draft = { tenant_id: string; department_id: string; roles: string[] };
type RowConfirm = { kind: 'lock' | 'signOut' | 'reset'; user: AdminUser };

const INPUT =
  'w-full min-w-[7rem] rounded-md border border-border-input bg-surface px-2 py-1 text-base sm:text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary disabled:opacity-60';
const ICON_BUTTON = 'btn-dash !px-2';

const isSso = (user: AdminUser) => user.username.startsWith('sso:');

/** Every account with its tenant, department and roles. Self-registered ones can be changed, locked, signed out, given a new password or
 * handled several at a time; `AUTH_USERS` ones are shown read-only. */
export const AdminUsers: React.FC = () => {
  const [lang] = useLang();
  const [directory, setDirectory] = useState<AdminDirectory | null>(null);
  const [org, setOrg] = useState<OrgTenant[]>([]);
  const [error, setError] = useState<AdminError | Error | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [onlyPending, setOnlyPending] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const [issued, setIssued] = useState<{ title: string; credentials: IssuedCredentials } | null>(null);
  const [rowConfirm, setRowConfirm] = useState<RowConfirm | null>(null);
  const [bulkConfirm, setBulkConfirm] = useState<'lock' | 'sign_out' | null>(null);
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveTenant, setMoveTenant] = useState('');
  const [moveDepartment, setMoveDepartment] = useState('');
  const [bulkBusy, setBulkBusy] = useState(false);

  const load = useCallback(async (keepDrafts = false) => {
    try {
      const [directoryNow, orgNow] = await Promise.all([listAdminUsers(), getOrg().catch(() => null)]);
      setDirectory(directoryNow);
      if (orgNow) setOrg(orgNow);
      if (!keepDrafts) setDrafts({}); // a reload because the organization changed must not throw away what is being typed in a row
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e : new Error(String(e)));
    }
  }, []);

  useEffect(() => {
    void load();
    return onOrgChange(() => void load(true)); // a department created on another page (or tab) is in the pickers now, not after a refresh
  }, [load]);

  const draftOf = (user: AdminUser): Draft => drafts[user.username] ?? { tenant_id: user.tenant_id, department_id: user.department_id, roles: user.roles };
  const edit = (user: AdminUser, patch: Partial<Draft>) => setDrafts((all) => ({ ...all, [user.username]: { ...draftOf(user), ...patch } }));
  const reason = (e: unknown) => (e instanceof Error ? e.message : String(e));

  const apply = async (user: AdminUser, changes: UserChanges) => {
    setBusy(user.username);
    try {
      await updateAdminUser(user.username, changes);
      toast.success(t(lang, 'admin.saved', { user: user.username }));
      await load();
    } catch (e: unknown) {
      toast.error(t(lang, 'admin.saveFailed', { user: user.username, error: reason(e) }));
    } finally {
      setBusy(null);
    }
  };

  const runRowConfirm = async () => {
    if (!rowConfirm) return;
    const { kind, user } = rowConfirm;
    setBusy(user.username);
    try {
      if (kind === 'lock') {
        await updateAdminUser(user.username, { disabled: true });
        toast.success(t(lang, 'admin.saved', { user: user.username }));
      } else if (kind === 'signOut') {
        await signOutUser(user.username);
        toast.success(t(lang, 'admin.signOut.done', { user: user.username }));
      } else {
        setIssued({ title: t(lang, 'admin.creds.titleReset', { user: user.username }), credentials: await resetCredentials(user.username) });
      }
      setRowConfirm(null);
      await load();
    } catch (e: unknown) {
      toast.error(t(lang, 'admin.actionFailed', { user: user.username, error: reason(e) }));
    } finally {
      setBusy(null);
    }
  };

  const runBulk = async (action: BulkActionName, target: { tenant_id?: string; department_id?: string } = {}) => {
    setBulkBusy(true);
    try {
      const result = await bulkUsers({ usernames: [...selected], action, ...target });
      const skipped = result.skipped.length;
      const list = result.skipped.map((s) => `${s.username} (${t(lang, `admin.bulk.skip.${s.reason}` as MessageKey)})`).join(', ');
      const text = `${t(lang, 'admin.bulk.result', { done: result.done.length, skipped })}${skipped ? ` ${t(lang, 'admin.bulk.skipList', { list })}` : ''}`;
      (result.done.length ? toast.success : toast.error)(text);
      setSelected(new Set());
      setBulkConfirm(null);
      setMoveOpen(false);
      await load();
    } catch (e: unknown) {
      toast.error(t(lang, 'admin.actionFailed', { user: String(selected.size), error: reason(e) }));
    } finally {
      setBulkBusy(false);
    }
  };

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (directory?.users ?? []).filter(
      (u) => (!onlyPending || u.pending) && (!needle || `${u.username} ${u.display_name}`.toLowerCase().includes(needle))
    );
  }, [directory, query, onlyPending]);

  const selectable = shown.filter((u) => u.source !== 'env');
  const allSelected = selectable.length > 0 && selectable.every((u) => selected.has(u.username));
  const toggle = (username: string, on: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(username);
      else next.delete(username);
      return next;
    });

  if (error) {
    const forbidden = error instanceof AdminError && error.status === 403;
    return <p role="alert" className="text-sm text-accent-error">{forbidden ? t(lang, 'admin.forbidden') : t(lang, 'admin.loadFailed', { error: error.message })}</p>;
  }
  if (!directory) {
    return (
      <div className="flex items-center gap-2 text-sm text-foreground-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'admin.loading')}
      </div>
    );
  }

  const confirmCopy: Record<RowConfirm['kind'], { title: MessageKey; body: MessageKey; label: MessageKey; danger: boolean }> = {
    lock: { title: 'admin.lock.title', body: 'admin.lockConfirm', label: 'admin.lock', danger: true },
    signOut: { title: 'admin.signOut.title', body: 'admin.signOut.body', label: 'admin.action.signOut', danger: false },
    reset: { title: 'admin.reset.title', body: 'admin.reset.body', label: 'admin.reset.submit', danger: true },
  };

  return (
    <section aria-label={t(lang, 'admin.title')} className="space-y-3" data-testid="admin-users">
      <div className="flex flex-wrap items-center gap-3">
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t(lang, 'admin.search')} aria-label={t(lang, 'admin.search')} className={`${INPUT} max-w-xs`} />
        <label className="flex items-center gap-2 text-xs text-foreground-secondary">
          <input type="checkbox" checked={onlyPending} onChange={(e) => setOnlyPending(e.target.checked)} />
          {t(lang, 'admin.onlyPending')}
        </label>
        <span className="text-xs text-foreground-muted">{t(lang, 'admin.count', { shown: shown.length, total: directory.users.length })}</span>
        <button type="button" className="btn-primary ml-auto" onClick={() => setCreating(true)}>
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          {t(lang, 'admin.create.button')}
        </button>
      </div>

      {selected.size > 0 && (
        <div role="region" aria-label={t(lang, 'admin.bulk.selected', { count: selected.size })} className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface-raised px-3 py-2">
          <span className="text-sm font-semibold text-foreground">{t(lang, 'admin.bulk.selected', { count: selected.size })}</span>
          <button type="button" className="btn-dash" onClick={() => setBulkConfirm('lock')}><Lock className="h-3.5 w-3.5" aria-hidden="true" />{t(lang, 'admin.bulk.lock')}</button>
          <button type="button" className="btn-dash" onClick={() => void runBulk('unlock')} disabled={bulkBusy}><LockOpen className="h-3.5 w-3.5" aria-hidden="true" />{t(lang, 'admin.bulk.unlock')}</button>
          <button type="button" className="btn-dash" onClick={() => setMoveOpen(true)}>{t(lang, 'admin.bulk.move')}</button>
          <button type="button" className="btn-dash" onClick={() => setBulkConfirm('sign_out')}><LogOut className="h-3.5 w-3.5" aria-hidden="true" />{t(lang, 'admin.bulk.signOut')}</button>
          <button type="button" className="btn-dash ml-auto" onClick={() => setSelected(new Set())}>{t(lang, 'admin.bulk.clear')}</button>
        </div>
      )}

      <div className="relative overflow-x-auto rounded-lg border border-border">{/* relative: the sr-only header cell is absolute and would otherwise widen the page past this scroller */}
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-raised text-foreground-muted">
            <tr>
              <th scope="col" className="w-8 px-3 py-2">
                <input type="checkbox" checked={allSelected} disabled={selectable.length === 0} onChange={(e) => setSelected(e.target.checked ? new Set(selectable.map((u) => u.username)) : new Set())} aria-label={t(lang, 'admin.bulk.selectAll')} />
              </th>
              <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'admin.colUser')}</th>
              <th scope="col" className="px-3 py-2 font-semibold">{`${t(lang, 'admin.colTenant')} / ${t(lang, 'admin.colDepartment')}`}</th>
              <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'admin.colRoles')}</th>
              <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'admin.colStatus')}</th>
              <th scope="col" className="px-3 py-2"><span className="sr-only">{t(lang, 'admin.save')}</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {shown.map((user) => {
              const readOnly = user.source === 'env';
              const draft = draftOf(user);
              const changes = readOnly ? {} : diffUser(user, draft);
              const working = busy === user.username;
              return (
                <tr key={`${user.source}:${user.username}`} className="align-top hover:bg-surface-raised/50">
                  <td className="px-3 py-2">
                    {!readOnly && (
                      <input type="checkbox" checked={selected.has(user.username)} onChange={(e) => toggle(user.username, e.target.checked)} aria-label={t(lang, 'admin.bulk.select', { user: user.username })} />
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <p className="font-medium text-foreground">{user.username}</p>
                    {user.display_name && user.display_name !== user.username && <p className="text-foreground-muted">{user.display_name}</p>}
                    {readOnly && <p className="text-foreground-muted">{t(lang, 'admin.envManaged')}</p>}
                  </td>
                  <td className="px-3 py-2">
                    <ScopePicker
                      org={org}
                      tenant={draft.tenant_id}
                      department={draft.department_id}
                      disabled={readOnly || working}
                      onChange={(tenant_id, department_id) => edit(user, { tenant_id, department_id })}
                      tenantLabel={`${t(lang, 'admin.colTenant')} ${user.username}`}
                      departmentLabel={`${t(lang, 'admin.colDepartment')} ${user.username}`}
                      unregisteredMark={t(lang, 'admin.org.unregistered')}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-x-3 gap-y-1">
                      {directory.roles.map((role) => (
                        <label key={role} className="flex items-center gap-1.5 text-foreground-secondary">
                          <input
                            type="checkbox"
                            checked={draft.roles.includes(role)}
                            disabled={readOnly || working}
                            onChange={(e) => edit(user, { roles: e.target.checked ? [...draft.roles, role] : draft.roles.filter((r) => r !== role) })}
                          />
                          {role}
                        </label>
                      ))}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    {user.disabled ? <span className="font-semibold text-accent-error">{t(lang, 'admin.locked')}</span> : user.pending ? <span className="font-semibold text-foreground-secondary">{t(lang, 'admin.pending')}</span> : <span className="text-foreground-secondary">{t(lang, 'admin.active')}</span>}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {!readOnly && (
                      <div className="flex flex-wrap justify-end gap-2">
                        <button type="button" className="btn-dash" disabled={working || !draft.tenant_id || !draft.department_id || Object.keys(changes).length === 0} onClick={() => void apply(user, changes)}>
                          {working ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
                          {t(lang, 'admin.save')}
                        </button>
                        <button type="button" className="btn-dash" disabled={working} onClick={() => (user.disabled ? void apply(user, { disabled: false }) : setRowConfirm({ kind: 'lock', user }))}>
                          {user.disabled ? <LockOpen className="h-3.5 w-3.5" aria-hidden="true" /> : <Lock className="h-3.5 w-3.5" aria-hidden="true" />}
                          {t(lang, user.disabled ? 'admin.unlock' : 'admin.lock')}
                        </button>
                        <button type="button" className={ICON_BUTTON} disabled={working} onClick={() => setRowConfirm({ kind: 'signOut', user })} aria-label={`${t(lang, 'admin.action.signOut')}: ${user.username}`} title={t(lang, 'admin.action.signOut')}>
                          <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
                        </button>
                        {!isSso(user) && (
                          <button type="button" className={ICON_BUTTON} disabled={working} onClick={() => setRowConfirm({ kind: 'reset', user })} aria-label={`${t(lang, 'admin.action.reset')}: ${user.username}`} title={t(lang, 'admin.action.reset')}>
                            <KeyRound className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <CreateAccountDialog
        open={creating}
        directory={directory}
        org={org}
        onClose={() => setCreating(false)}
        onCreated={(credentials) => {
          setCreating(false);
          setIssued({ title: t(lang, 'admin.creds.titleCreated', { user: credentials.user.username }), credentials });
          void load();
        }}
      />
      <CredentialsDialog title={issued?.title ?? ''} credentials={issued?.credentials ?? null} onClose={() => setIssued(null)} />
      <ConfirmDialog
        open={rowConfirm !== null}
        title={rowConfirm ? t(lang, confirmCopy[rowConfirm.kind].title, { user: rowConfirm.user.username }) : ''}
        body={rowConfirm ? t(lang, confirmCopy[rowConfirm.kind].body, { user: rowConfirm.user.username }) : ''}
        confirmLabel={rowConfirm ? t(lang, confirmCopy[rowConfirm.kind].label) : ''}
        danger={rowConfirm ? confirmCopy[rowConfirm.kind].danger : false}
        busy={busy !== null}
        onConfirm={() => void runRowConfirm()}
        onCancel={() => setRowConfirm(null)}
      />
      <ConfirmDialog
        open={bulkConfirm !== null}
        title={bulkConfirm === 'lock' ? t(lang, 'admin.bulk.lockTitle', { count: selected.size }) : t(lang, 'admin.bulk.signOutTitle', { count: selected.size })}
        body={bulkConfirm === 'lock' ? t(lang, 'admin.bulk.lockBody') : t(lang, 'admin.bulk.signOutBody')}
        confirmLabel={bulkConfirm === 'lock' ? t(lang, 'admin.bulk.lock') : t(lang, 'admin.bulk.signOut')}
        danger={bulkConfirm === 'lock'}
        busy={bulkBusy}
        onConfirm={() => void runBulk(bulkConfirm ?? 'sign_out')}
        onCancel={() => setBulkConfirm(null)}
      />
      <AdminDialog open={moveOpen} title={t(lang, 'admin.bulk.moveTitle', { count: selected.size })} onClose={() => setMoveOpen(false)} canClose={!bulkBusy}>
        <form
          noValidate
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (moveTenant.trim() && moveDepartment.trim()) void runBulk('move', { tenant_id: moveTenant.trim(), department_id: moveDepartment.trim() });
          }}
        >
          <ScopePicker
            org={org}
            tenant={moveTenant}
            department={moveDepartment}
            disabled={bulkBusy}
            onChange={(tenant, department) => {
              setMoveTenant(tenant);
              setMoveDepartment(department);
            }}
            tenantLabel={t(lang, 'admin.colTenant')}
            departmentLabel={t(lang, 'admin.colDepartment')}
            unregisteredMark={t(lang, 'admin.org.unregistered')}
            className={`${INPUT} !text-base sm:!text-sm`}
          />
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn-dash" onClick={() => setMoveOpen(false)} disabled={bulkBusy}>{t(lang, 'admin.dialog.cancel')}</button>
            <button type="submit" className="btn-primary" disabled={bulkBusy || !moveTenant.trim() || !moveDepartment.trim()}>
              {bulkBusy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
              {t(lang, 'admin.bulk.moveSubmit')}
            </button>
          </div>
        </form>
      </AdminDialog>
    </section>
  );
};
