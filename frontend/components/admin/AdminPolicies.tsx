'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { Check, Loader2, Pencil, X } from 'lucide-react';
import { AdminDialog } from './AdminDialog';
import { TENANT_DEFAULT, getOrg, getPolicies, setPolicy, type DepartmentPolicy, type OrgTenant, type PolicyList } from '../../lib/adminApi';
import { effectivePolicy } from '../../lib/adminConsole';
import { announceOrgChange, onOrgChange } from '../../lib/adminEvents';
import { t, useLang, type MessageKey } from '../../lib/i18n';
import { toast } from '../../lib/toast';
import { useAdminData } from '../../lib/useAdminData';

type Scope = { tenant: string; department: string; label: string };
type UploadChoice = 'inherit' | 'allow' | 'deny';

const toChoice = (value: boolean | null | undefined): UploadChoice => (value === true ? 'allow' : value === false ? 'deny' : 'inherit');
const fromChoice = (choice: UploadChoice): boolean | null => (choice === 'allow' ? true : choice === 'deny' ? false : null);

/** What each department may use, side by side: one row per tenant default and per department, one column per agent and one for the knowledge-base
 * upload, showing what the department REALLY gets (its own setting, else its tenant's, else everything). */
export const AdminPolicies: React.FC = () => {
  const [lang] = useLang();
  const orgFetcher = useCallback(() => getOrg(), []);
  const policyFetcher = useCallback(() => getPolicies(), []);
  const org = useAdminData(orgFetcher);
  const policies = useAdminData(policyFetcher);
  const [editing, setEditing] = useState<Scope | null>(null);
  const [useDefault, setUseDefault] = useState(true);
  const [agents, setAgents] = useState<string[]>([]);
  const [upload, setUpload] = useState<UploadChoice>('inherit');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const { reload: reloadOrg } = org;
  const { reload: reloadPolicies } = policies;

  useEffect(() => onOrgChange(() => {
    void reloadOrg();
    void reloadPolicies();
  }), [reloadOrg, reloadPolicies]);

  const list: PolicyList | null = policies.data;
  const tenants: OrgTenant[] = (org.data ?? []).filter((x) => !x.pending);
  const roles = (list?.upload_roles ?? []).join(', ');

  const open = (scope: Scope) => {
    const own: DepartmentPolicy | undefined = list?.policies.find((p) => p.tenant_id === scope.tenant && p.department_id === scope.department);
    setEditing(scope);
    setUseDefault(!own || own.allowed_agents === null);
    setAgents(own?.allowed_agents ?? list?.agents ?? []);
    setUpload(toChoice(own?.can_upload_knowledge));
    setError('');
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editing) return;
    if (!useDefault && agents.length === 0) return setError(t(lang, 'admin.policy.needAgent'));
    setBusy(true);
    setError('');
    try {
      await setPolicy(editing.tenant, editing.department, { allowed_agents: useDefault ? null : agents, can_upload_knowledge: fromChoice(upload) });
      toast.success(t(lang, 'admin.policy.saved', { scope: editing.label }));
      setEditing(null);
      await reloadPolicies();
      announceOrgChange();
    } catch (e: unknown) {
      setError(t(lang, 'admin.policy.saveFailed', { error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusy(false);
    }
  };

  const agentName = (agent: string) => t(lang, `admin.policy.agent.${agent}` as MessageKey);
  const failure = org.error ?? policies.error;

  const row = (scope: Scope, key: string, nested: boolean) => {
    const effective = effectivePolicy(list?.policies ?? [], scope.tenant, scope.department);
    return (
      <tr key={key} className="hover:bg-surface-raised/50">
        <td className={`px-3 py-2 ${nested ? 'pl-7 text-foreground' : 'font-semibold text-foreground'}`}>{scope.label}</td>
        {(list?.agents ?? []).map((agent) => {
          const allowed = effective.agents === null || effective.agents.includes(agent);
          const inherited = effective.agentsFrom === 'tenant';
          const title = `${agentName(agent)}: ${t(lang, allowed ? 'admin.policy.yes' : 'admin.policy.no')}${inherited ? ` (${t(lang, 'admin.policy.inherited')})` : ''}`;
          return (
            <td key={agent} className="px-3 py-2 text-center" title={title}>
              {allowed ? <Check className="mx-auto h-4 w-4 text-foreground" aria-hidden="true" /> : <X className="mx-auto h-4 w-4 text-foreground-muted" aria-hidden="true" />}
              {inherited && <span className="block text-center text-[10px] leading-3 text-foreground-muted" aria-hidden="true">{t(lang, 'admin.policy.inherited')}</span>}
              <span className="sr-only">{title}</span>
            </td>
          );
        })}
        <td className="whitespace-nowrap px-3 py-2 text-foreground-secondary">
          {effective.upload === null ? t(lang, 'admin.policy.upload.role', { roles }) : t(lang, effective.upload ? 'admin.policy.upload.allow' : 'admin.policy.upload.deny')}
          {effective.uploadFrom === 'tenant' && <span className="text-foreground-muted">{` · ${t(lang, 'admin.policy.inherited')}`}</span>}
        </td>
        <td className="px-3 py-2 text-right">
          <button type="button" className="btn-dash whitespace-nowrap" onClick={() => open(scope)} aria-label={`${t(lang, 'admin.policy.edit')}: ${scope.label}`}>
            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
            {t(lang, 'admin.policy.edit')}
          </button>
        </td>
      </tr>
    );
  };

  return (
    <section aria-labelledby="org-policies" className="space-y-2" data-testid="admin-policies">
      <h2 id="org-policies" className="text-lg font-bold text-foreground">{t(lang, 'admin.policy.title')}</h2>
      <p className="max-w-3xl text-sm text-foreground-secondary">{t(lang, 'admin.policy.subtitle')}</p>
      {failure && <p role="alert" className="text-sm text-accent-error">{t(lang, 'admin.policy.loadFailed', { error: failure })}</p>}
      {!list && !failure && (
        <div className="flex items-center gap-2 text-sm text-foreground-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> {t(lang, 'admin.policy.loading')}
        </div>
      )}
      {list && (
        <div className="relative overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-xs">
            <thead className="bg-surface-raised text-foreground-muted">
              <tr>
                <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'admin.policy.colScope')}</th>
                {list.agents.map((agent) => <th key={agent} scope="col" className="px-3 py-2 text-center font-semibold">{agentName(agent)}</th>)}
                <th scope="col" className="px-3 py-2 font-semibold">{t(lang, 'admin.policy.colUpload')}</th>
                <th scope="col" className="px-3 py-2"><span className="sr-only">{t(lang, 'admin.policy.edit')}</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {tenants.flatMap((tenant) => [
                row({ tenant: tenant.id, department: TENANT_DEFAULT, label: `${tenant.name || tenant.id} · ${t(lang, 'admin.policy.tenantDefault')}` }, `${tenant.id}/*`, false),
                ...tenant.departments.map((d) => row({ tenant: tenant.id, department: d.id, label: `${tenant.name || tenant.id} / ${d.name || d.id}` }, `${tenant.id}/${d.id}`, true)),
              ])}
            </tbody>
          </table>
        </div>
      )}

      <AdminDialog open={editing !== null} title={editing ? t(lang, 'admin.policy.editTitle', { scope: editing.label }) : ''} onClose={() => setEditing(null)} canClose={!busy}>
        <form onSubmit={(e) => void save(e)} noValidate className="space-y-4">
          <fieldset className="space-y-2">
            <legend className="text-xs font-semibold text-foreground-secondary">{t(lang, 'admin.policy.agentsLegend')}</legend>
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input type="checkbox" checked={useDefault} disabled={busy} onChange={(e) => setUseDefault(e.target.checked)} />
              {t(lang, 'admin.policy.useDefault')}
            </label>
            {!useDefault && (
              <div className="space-y-1 pl-6">
                {(list?.agents ?? []).map((agent) => (
                  <label key={agent} className="flex items-center gap-2 text-sm text-foreground-secondary">
                    <input type="checkbox" checked={agents.includes(agent)} disabled={busy} onChange={(e) => setAgents(e.target.checked ? [...agents, agent] : agents.filter((a) => a !== agent))} />
                    {agentName(agent)}
                  </label>
                ))}
              </div>
            )}
          </fieldset>
          <fieldset className="space-y-2">
            <legend className="text-xs font-semibold text-foreground-secondary">{t(lang, 'admin.policy.uploadLegend')}</legend>
            {(['inherit', 'allow', 'deny'] as UploadChoice[]).map((choice) => (
              <label key={choice} className="flex items-center gap-2 text-sm text-foreground-secondary">
                <input type="radio" name="policy-upload" checked={upload === choice} disabled={busy} onChange={() => setUpload(choice)} />
                {choice === 'inherit' ? t(lang, 'admin.policy.uploadInherit') : t(lang, choice === 'allow' ? 'admin.policy.upload.allow' : 'admin.policy.upload.deny')}
              </label>
            ))}
            <p className="text-xs text-foreground-muted">{t(lang, 'admin.policy.uploadExplain', { roles })}</p>
          </fieldset>
          {error && <p role="alert" className="rounded-md border border-accent-error/30 bg-accent-error/10 px-3 py-2 text-sm text-accent-error">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn-dash" onClick={() => setEditing(null)} disabled={busy}>{t(lang, 'admin.dialog.cancel')}</button>
            <button type="submit" className="btn-primary" disabled={busy}>
              {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
              {t(lang, 'admin.org.save')}
            </button>
          </div>
        </form>
      </AdminDialog>
    </section>
  );
};
