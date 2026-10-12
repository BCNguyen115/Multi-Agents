'use client';

import React from 'react';
import type { OrgTenant } from '../../lib/adminApi';

const SELECT =
  'w-full min-w-[7rem] rounded-md border border-border-input bg-surface px-2 py-1 text-base sm:text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary disabled:opacity-60';

/**
 * Pick a tenant, then one of ITS departments: two selects fed by the organization registry, so a department created a moment ago is on the
 * list as soon as the registry is reloaded, and a department can never be paired with the wrong tenant. What the account has now stays
 * selectable even when it is not in the registry (an id only accounts use), marked so.
 */
export function ScopePicker({
  org, tenant, department, onChange, disabled = false, tenantLabel, departmentLabel, unregisteredMark, className = SELECT,
}: {
  org: OrgTenant[];
  tenant: string;
  department: string;
  onChange: (tenant: string, department: string) => void;
  disabled?: boolean;
  tenantLabel: string;
  departmentLabel: string;
  /** Appended to an option that is not in the registry. */
  unregisteredMark: string;
  className?: string;
}) {
  const known = org.find((t) => t.id === tenant);
  const departments = known?.departments ?? [];
  const tenantOptions = known || !tenant ? org : [...org, { id: tenant, name: '', users: 0, registered: false, pending: false, departments: [] } as OrgTenant];
  const departmentOptions = departments.some((d) => d.id === department) || !department ? departments : [...departments, { id: department, name: '', users: 0, registered: false }];
  const mark = (registered: boolean) => (registered ? '' : ` (${unregisteredMark})`);
  return (
    <div className="flex flex-wrap gap-2">
      <select
        value={tenant}
        disabled={disabled}
        aria-label={tenantLabel}
        onChange={(e) => onChange(e.target.value, org.find((t) => t.id === e.target.value)?.departments[0]?.id ?? '')}
        className={className}
      >
        {!tenant && <option value="" />}
        {tenantOptions.map((t) => (
          <option key={t.id} value={t.id}>{`${t.name || t.id}${mark(t.registered || t.pending)}`}</option>
        ))}
      </select>
      <select value={department} disabled={disabled} aria-label={departmentLabel} onChange={(e) => onChange(tenant, e.target.value)} className={className}>
        {!department && <option value="" />}
        {departmentOptions.map((d) => (
          <option key={d.id} value={d.id}>{`${d.name || d.id}${mark(d.registered || known?.pending === true)}`}</option>
        ))}
      </select>
    </div>
  );
}
