'use client';

import React, { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { AdminDialog } from './AdminDialog';
import type { IssuedCredentials } from '../../lib/adminApi';
import { t, useLang } from '../../lib/i18n';

function Secret({ label, value }: { label: string; value: string }) {
  const [lang] = useLang();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* no clipboard permission: the value is selectable on screen */
    }
  };
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold text-foreground-secondary">{label}</p>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 select-all break-all rounded-md border border-border bg-surface-raised px-2.5 py-2 font-mono text-sm text-foreground">{value}</code>
        <button type="button" className="btn-dash shrink-0" onClick={() => void copy()} aria-label={`${t(lang, 'admin.creds.copy')}: ${label}`}>
          {copied ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
          {copied ? t(lang, 'admin.creds.copied') : t(lang, 'admin.creds.copy')}
        </button>
      </div>
    </div>
  );
}

/** The password and recovery key of an account just created or reset. They are shown here once and never again (the server keeps hashes). */
export function CredentialsDialog({ title, credentials, onClose }: { title: string; credentials: IssuedCredentials | null; onClose: () => void }) {
  const [lang] = useLang();
  return (
    <AdminDialog open={credentials !== null} title={title} onClose={onClose}>
      {credentials && (
        <div className="space-y-4">
          <p role="status" className="rounded-md border border-border bg-surface-raised px-3 py-2 text-sm text-foreground-secondary">{t(lang, 'admin.creds.warning')}</p>
          <Secret label={t(lang, 'admin.creds.password')} value={credentials.temporary_password} />
          <Secret label={t(lang, 'admin.creds.recovery')} value={credentials.recovery_key} />
          <div className="flex justify-end">
            <button type="button" className="btn-primary" onClick={onClose}>{t(lang, 'admin.creds.done')}</button>
          </div>
        </div>
      )}
    </AdminDialog>
  );
}
