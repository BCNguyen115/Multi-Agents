'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Building2, Loader2, Pencil, Plus, Trash2 } from 'lucide-react';
import { AdminDialog } from './AdminDialog';
import { ORG_ID, createDepartment, createTenant, deleteDepartment, deleteTenant, getOrg, renameDepartment, renameTenant, type OrgTenant } from '../../lib/adminApi';
import { announceOrgChange, onOrgChange } from '../../lib/adminEvents';
import { t, useLang } from '../../lib/i18n';
import { toast } from '../../lib/toast';

type Target = { kind: 'tenant' } | { kind: 'department'; tenant: string };
/** What a rename or a delete is about: a tenant, or a department of `tenant`. `registered` = it is in the registry (else renaming it registers it). */
type Subject = { kind: 'tenant'; id: string; name: string; registered: boolean; users: number } | { kind: 'department'; tenant: string; id: string; name: string; registered: boolean; users: number };

/** Where accounts may go when `subject` is deleted: the other departments of its tenant, or any department of another tenant. `tenant/department`. */
function movePlaces(org: OrgTenant[], subject: Subject): { value: string; label: string }[] {
  const places: { value: string; label: string }[] = [];
  for (const t of org) {
    if (subject.kind === 'tenant' ? t.id === subject.id : t.id !== subject.tenant) continue;
    for (const d of t.departments) {
      if (subject.kind === 'department' && d.id === subject.id) continue;
      places.push({ value: subject.kind === 'tenant' ? `${t.id}/${d.id}` : d.id, label: `${t.name || t.id} / ${d.name || d.id}` });
    }
  }
  return places;
}

const INPUT =
  'w-full rounded-md border border-border-input bg-surface px-2 py-1.5 text-base sm:text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary disabled:opacity-60';
const ICON_BUTTON =
  'inline-flex h-6 w-6 [@media(pointer:coarse)]:h-9 [@media(pointer:coarse)]:w-9 shrink-0 cursor-pointer items-center justify-center rounded-full text-foreground-muted transition-colors hover:bg-surface-raised hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary disabled:opacity-50';

/** The tenants and departments (a registry the accounts do not have to follow), with the buttons that create, rename and delete them. */
export const AdminOrg: React.FC<{ onChanged?: () => void }> = ({ onChanged }) => {
  const [lang] = useLang();
  const [org, setOrg] = useState<OrgTenant[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<Target | null>(null);
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [idError, setIdError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [renaming, setRenaming] = useState<Subject | null>(null);
  const [newName, setNewName] = useState('');
  const [doomed, setDoomed] = useState<Subject | null>(null);
  const [moveTo, setMoveTo] = useState('');

  const load = useCallback(async () => {
    try {
      setOrg(await getOrg());
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
    return onOrgChange(() => void load()); // another tab (or the policies table below) changed the organization
  }, [load]);

  const open = (next: Target) => {
    setTarget(next);
    setId('');
    setName('');
    setIdError(false);
  };

  const reason = (e: unknown) => (e instanceof Error ? e.message : String(e));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!target) return;
    const cleanId = id.trim();
    if (!ORG_ID.test(cleanId)) {
      setIdError(true);
      return;
    }
    setBusy(true);
    try {
      if (target.kind === 'tenant') {
        await createTenant(cleanId, name.trim());
        toast.success(t(lang, 'admin.org.tenantCreated', { id: cleanId }));
      } else {
        await createDepartment(target.tenant, cleanId, name.trim());
        toast.success(t(lang, 'admin.org.departmentCreated', { id: cleanId, tenant: target.tenant }));
      }
      setTarget(null);
      await load();
      announceOrgChange(); // the pickers of the other admin pages offer the new ids at once
      onChanged?.();
    } catch (e: unknown) {
      toast.error(t(lang, 'admin.org.createFailed', { error: reason(e) }));
    } finally {
      setBusy(false);
    }
  };

  const startDelete = (subject: Subject) => {
    setMoveTo('');
    setDoomed(subject);
  };

  const startRename = (subject: Subject) => {
    setRenaming(subject);
    setNewName(subject.name);
  };

  const saveName = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!renaming) return;
    setBusy(true);
    try {
      await (renaming.kind === 'tenant' ? renameTenant(renaming.id, newName.trim()) : renameDepartment(renaming.tenant, renaming.id, newName.trim()));
      toast.success(t(lang, 'admin.org.renamed', { id: renaming.id }));
      setRenaming(null);
      await load();
      announceOrgChange();
      onChanged?.();
    } catch (e: unknown) {
      toast.error(t(lang, 'admin.org.actionFailed', { error: reason(e) }));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!doomed) return;
    setBusy(true);
    try {
      const target = doomed.users > 0 ? moveTo : undefined;
      await (doomed.kind === 'tenant' ? deleteTenant(doomed.id, target) : deleteDepartment(doomed.tenant, doomed.id, target));
      toast.success(t(lang, 'admin.org.deleted', { id: doomed.id }));
      setDoomed(null);
      await load();
      announceOrgChange();
      onChanged?.();
    } catch (e: unknown) {
      toast.error(t(lang, 'admin.org.actionFailed', { error: reason(e) }));
    } finally {
      setBusy(false);
    }
  };

  const form = (
    <form onSubmit={(e) => void submit(e)} noValidate className="mt-2 grid gap-2 rounded-lg border border-border bg-surface-raised/40 p-3 sm:grid-cols-[1fr_1fr_auto] sm:items-start" data-testid="org-form">
      <label className="space-y-1 text-xs text-foreground-secondary">
        <span className="font-semibold">{t(lang, 'admin.org.id')}</span>
        <input value={id} onChange={(e) => { setId(e.target.value); setIdError(false); }} autoFocus disabled={busy} aria-invalid={idError} aria-describedby="org-id-hint" className={INPUT} />
        <span id="org-id-hint" role={idError ? 'alert' : undefined} className={idError ? 'text-accent-error' : 'text-foreground-muted'}>
          {idError ? t(lang, 'admin.org.badId') : t(lang, 'admin.org.idHint')}
        </span>
      </label>
      <label className="space-y-1 text-xs text-foreground-secondary">
        <span className="font-semibold">{t(lang, 'admin.org.name')}</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} disabled={busy} className={INPUT} />
      </label>
      <div className="flex gap-2 sm:pt-5">{/* pt-5 = the height of a field's label: the buttons sit on the inputs' row, whatever the hint under the first one says */}
        <button type="submit" className="btn-primary" disabled={busy || !id.trim()}>
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          {t(lang, 'admin.org.create')}
        </button>
        <button type="button" className="btn-dash" disabled={busy} onClick={() => setTarget(null)}>
          {t(lang, 'admin.org.cancel')}
        </button>
      </div>
    </form>
  );

  return (
    <section aria-label={t(lang, 'admin.org.title')} className="space-y-3" data-testid="admin-org">
      {error && <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.org.loadFailed', { error })}</p>}
      {!error && !org && (
        <div className="flex items-center gap-2 text-sm text-foreground-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'admin.org.loading')}
        </div>
      )}
      <ul className="grid gap-3 lg:grid-cols-2">
        {org?.map((tenant) => {
          const tenantSubject: Subject = { kind: 'tenant', id: tenant.id, name: tenant.name, registered: tenant.registered, users: tenant.users };
          return (
            <li key={tenant.id} className="rounded-lg border border-border p-3" data-testid={`org-tenant-${tenant.id}`}>
              <div className="flex flex-wrap items-start gap-2">
                <Building2 className="mt-0.5 h-4 w-4 shrink-0 text-accent-primary" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-foreground" title={tenant.id}>{tenant.name || tenant.id}</p>
                  <p className="break-words text-xs text-foreground-muted">
                    {tenant.name && <span className="font-mono">{tenant.id} · </span>}
                    {t(lang, 'admin.org.users', { count: tenant.users })}
                    {tenant.pending && ` · ${t(lang, 'admin.org.pending')}`}
                    {!tenant.registered && !tenant.pending && ` · ${t(lang, 'admin.org.unregistered')}`}
                  </p>
                </div>
                {!tenant.pending && (
                  <>
                    <button type="button" className={ICON_BUTTON} onClick={() => startRename(tenantSubject)} aria-label={`${t(lang, tenant.registered ? 'admin.org.rename' : 'admin.org.register')}: ${tenant.id}`} title={t(lang, tenant.registered ? 'admin.org.rename' : 'admin.org.register')}>
                      <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                    <button type="button" className={ICON_BUTTON} onClick={() => startDelete(tenantSubject)} aria-label={`${t(lang, 'admin.org.delete')}: ${tenant.id}`} title={t(lang, 'admin.org.delete')}>
                      <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                  </>
                )}
                {/* the pending tenant takes no departments, so its corner holds the button that creates a new tenant */}
                {tenant.pending ? (
                  <button type="button" className="btn-dash" onClick={() => open({ kind: 'tenant' })} aria-expanded={target?.kind === 'tenant'}>
                    <Plus className="h-3.5 w-3.5" aria-hidden="true" /> {t(lang, 'admin.org.newTenant')}
                  </button>
                ) : (
                  <button type="button" className="btn-dash" onClick={() => open({ kind: 'department', tenant: tenant.id })} aria-expanded={target?.kind === 'department' && target.tenant === tenant.id}>
                    <Plus className="h-3.5 w-3.5" aria-hidden="true" /> {t(lang, 'admin.org.newDepartment')}
                  </button>
                )}
              </div>
              {tenant.departments.length === 0 ? (
                <p className="mt-2 text-xs text-foreground-muted">{t(lang, 'admin.org.noDepartments')}</p>
              ) : (
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {tenant.departments.map((d) => {
                    const subject: Subject = { kind: 'department', tenant: tenant.id, id: d.id, name: d.name, registered: d.registered, users: d.users };
                    return (
                      <li
                        key={d.id}
                        className={`inline-flex items-center gap-1 rounded-full border py-0.5 pl-2.5 pr-1 text-xs ${d.registered ? 'border-border text-foreground' : 'border-dashed border-border text-foreground-muted'}`}
                        title={`${d.id} · ${t(lang, 'admin.org.users', { count: d.users })}${d.registered ? '' : ` · ${t(lang, 'admin.org.unregistered')}`}`}
                      >
                        <span>{d.name || d.id} <span className="text-foreground-muted">({d.users})</span></span>
                        {!tenant.pending && (
                          <>
                            <button type="button" className={ICON_BUTTON} onClick={() => startRename(subject)} aria-label={`${t(lang, d.registered ? 'admin.org.rename' : 'admin.org.register')}: ${tenant.id}/${d.id}`} title={t(lang, d.registered ? 'admin.org.rename' : 'admin.org.register')}>
                              <Pencil className="h-3 w-3" aria-hidden="true" />
                            </button>
                            <button type="button" className={ICON_BUTTON} onClick={() => startDelete(subject)} aria-label={`${t(lang, 'admin.org.delete')}: ${tenant.id}/${d.id}`} title={t(lang, 'admin.org.delete')}>
                              <Trash2 className="h-3 w-3" aria-hidden="true" />
                            </button>
                          </>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
              {((target?.kind === 'department' && target.tenant === tenant.id) || (target?.kind === 'tenant' && tenant.pending)) && form}
            </li>
          );
        })}
      </ul>

      <AdminDialog
        open={renaming !== null}
        title={renaming ? t(lang, renaming.registered ? 'admin.org.renameTitle' : 'admin.org.registerTitle', { id: renaming.id }) : ''}
        onClose={() => setRenaming(null)}
        canClose={!busy}
      >
        <form onSubmit={(e) => void saveName(e)} noValidate className="space-y-3">
          <label className="block space-y-1 text-xs text-foreground-secondary">
            <span className="font-semibold">{t(lang, 'admin.org.name')}</span>
            <input value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={100} autoFocus disabled={busy} className={`${INPUT} !text-base sm:!text-sm`} />
          </label>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-dash" onClick={() => setRenaming(null)} disabled={busy}>{t(lang, 'admin.org.cancel')}</button>
            <button type="submit" className="btn-primary" disabled={busy}>
              {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
              {t(lang, 'admin.org.save')}
            </button>
          </div>
        </form>
      </AdminDialog>
      <AdminDialog
        open={doomed !== null}
        title={doomed ? t(lang, doomed.kind === 'tenant' ? 'admin.org.deleteTenantTitle' : 'admin.org.deleteDepartmentTitle', { id: doomed.id }) : ''}
        onClose={() => setDoomed(null)}
        canClose={!busy}
      >
        {doomed && (
          <div className="space-y-3">
            <p className="text-sm text-foreground-secondary">{doomed.users > 0 ? t(lang, 'admin.org.deleteMoveBody', { count: doomed.users }) : t(lang, 'admin.org.deleteBody')}</p>
            {doomed.kind === 'tenant' && <p className="text-sm text-foreground-secondary">{t(lang, 'admin.org.deleteTenantCascade')}</p>}
            {doomed.users > 0 && (
              <label className="block space-y-1 text-xs text-foreground-secondary">
                <span className="font-semibold">{t(lang, 'admin.org.moveTo')}</span>
                <select value={moveTo} onChange={(e) => setMoveTo(e.target.value)} disabled={busy} className={`${INPUT} !text-base sm:!text-sm`}>
                  <option value="">{t(lang, 'admin.org.needTarget')}</option>
                  {movePlaces(org ?? [], doomed).map((place) => <option key={place.value} value={place.value}>{place.label}</option>)}
                </select>
                {movePlaces(org ?? [], doomed).length === 0 && <span role="alert" className="text-accent-error">{t(lang, 'admin.org.noTarget')}</span>}
              </label>
            )}
            <div className="flex justify-end gap-2 pt-1">
              <button type="button" className="btn-dash" onClick={() => setDoomed(null)} disabled={busy} autoFocus>{t(lang, 'admin.dialog.cancel')}</button>
              <button type="button" className="btn-dash border-accent-error/50 text-accent-error" onClick={() => void remove()} disabled={busy || (doomed.users > 0 && !moveTo)}>
                {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
                {t(lang, 'admin.org.delete')}
              </button>
            </div>
          </div>
        )}
      </AdminDialog>
    </section>
  );
};
