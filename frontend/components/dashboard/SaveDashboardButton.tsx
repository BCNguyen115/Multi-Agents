'use client';

import React, { useState } from 'react';
import { Check, Loader2, Save } from 'lucide-react';
import type { DashboardSpec } from '../../lib/types';
import { saveDashboard } from '../../lib/dashboardsApi';
import { t, useLang } from '../../lib/i18n';
import { toast } from '../../lib/toast';

/** Saves the dashboard (its spec and the uploaded file) on the server; it comes back with `/dashboards`. */
export const SaveDashboardButton: React.FC<{ spec: DashboardSpec }> = ({ spec }) => {
  const [lang] = useLang();
  const [state, setState] = useState<'idle' | 'saving' | 'saved'>('idle');
  // without a session the file is not on the server (a spec restored from the browser's copy): nothing to save it with
  const noFile = !spec.sessionId;

  const save = async () => {
    setState('saving');
    try {
      const saved = await saveDashboard(spec, spec.title);
      toast.success(t(lang, 'saved.saved', { title: saved.title }));
      setState('saved');
    } catch (error: unknown) {
      toast.error(t(lang, 'saved.saveFailed', { error: error instanceof Error ? error.message : String(error) }));
      setState('idle');
    }
  };

  return (
    <button
      type="button"
      onClick={() => void save()}
      disabled={noFile || state !== 'idle'}
      title={noFile ? t(lang, 'saved.saveNoFile') : t(lang, 'saved.save')}
      className="btn-dash disabled:opacity-50"
    >
      {state === 'saving' ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" /> : state === 'saved' ? <Check className="w-3.5 h-3.5 text-accent-verifier" aria-hidden="true" /> : <Save className="w-3.5 h-3.5 text-accent-primary" aria-hidden="true" />}
      <span className="hidden sm:inline">{t(lang, 'saved.save')}</span>
    </button>
  );
};
