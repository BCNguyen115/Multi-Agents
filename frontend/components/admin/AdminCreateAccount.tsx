'use client';

import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { AdminDialog } from './AdminDialog';
import { ScopePicker } from './ScopePicker';
import { createAccount, type AdminDirectory, type IssuedCredentials, type OrgTenant } from '../../lib/adminApi';
import { t, useLang } from '../../lib/i18n';

const USERNAME = /^[A-Za-z0-9._-]{3,32}$/;
const FIELD =
  'w-full rounded-md border border-border-input bg-surface px-2.5 py-1.5 text-base sm:text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary disabled:opacity-60';

/** Create an account: who, where (tenant and department) and with which roles. It returns the temporary password and recovery key for `onCreated`. */
export function CreateAccountDialog({
  open, directory, org, onClose, onCreated,
}: {
  open: boolean;
  directory: AdminDirectory;
  org: OrgTenant[];
  onClose: () => void;
  onCreated: (credentials: IssuedCredentials) => void;
}) {
  const [lang] = useLang();
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [tenant, setTenant] = useState('');
  const [department, setDepartment] = useState('');
  const [roles, setRoles] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setUsername('');
    setDisplayName('');
    setTenant('');
    setDepartment('');
    setRoles([]);
    setError('');
    setBusy(false);
  }, [open]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (!USERNAME.test(username.trim())) return setError(t(lang, 'admin.create.badName'));
    if (!tenant.trim() || !department.trim()) return setError(t(lang, 'admin.create.needScope'));
    setBusy(true);
    setError('');
    try {
      onCreated(await createAccount({ username: username.trim(), display_name: displayName.trim(), tenant_id: tenant.trim(), department_id: department.trim(), roles }));
    } catch (e: unknown) {
      setError(t(lang, 'admin.create.failed', { error: e instanceof Error ? e.message : String(e) }));
      setBusy(false);
    }
  };

  return (
    <AdminDialog open={open} title={t(lang, 'admin.create.title')} onClose={onClose} canClose={!busy}>
      <form onSubmit={(e) => void submit(e)} noValidate className="space-y-3">
        <p className="text-sm text-foreground-secondary">{t(lang, 'admin.create.note')}</p>
        <label className="block space-y-1 text-xs text-foreground-secondary">
          <span className="font-semibold">{t(lang, 'admin.create.username')}</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="off" maxLength={32} disabled={busy} className={FIELD} aria-describedby="create-username-hint" />
          <span id="create-username-hint" className="text-foreground-muted">{t(lang, 'admin.create.usernameHint')}</span>
        </label>
        <label className="block space-y-1 text-xs text-foreground-secondary">
          <span className="font-semibold">{t(lang, 'admin.create.displayName')}</span>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={64} disabled={busy} className={FIELD} />
        </label>
        <div className="space-y-1 text-xs text-foreground-secondary">
          <span className="font-semibold">{`${t(lang, 'admin.create.tenant')} / ${t(lang, 'admin.create.department')}`}</span>
          <ScopePicker
            org={org}
            tenant={tenant}
            department={department}
            disabled={busy}
            onChange={(nextTenant, nextDepartment) => {
              setTenant(nextTenant);
              setDepartment(nextDepartment);
            }}
            tenantLabel={t(lang, 'admin.create.tenant')}
            departmentLabel={t(lang, 'admin.create.department')}
            unregisteredMark={t(lang, 'admin.org.unregistered')}
            className={FIELD}
          />
        </div>
        <fieldset className="space-y-1">
          <legend className="text-xs font-semibold text-foreground-secondary">{t(lang, 'admin.create.roles')}</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {directory.roles.map((role) => (
              <label key={role} className="flex items-center gap-1.5 text-xs text-foreground-secondary">
                <input type="checkbox" checked={roles.includes(role)} disabled={busy} onChange={(e) => setRoles(e.target.checked ? [...roles, role] : roles.filter((r) => r !== role))} />
                {role}
              </label>
            ))}
          </div>
        </fieldset>
        {error && <p role="alert" className="rounded-md border border-accent-error/30 bg-accent-error/10 px-3 py-2 text-sm text-accent-error">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn-dash" onClick={onClose} disabled={busy}>{t(lang, 'admin.dialog.cancel')}</button>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
            {t(lang, 'admin.create.submit')}
          </button>
        </div>
      </form>
    </AdminDialog>
  );
}
