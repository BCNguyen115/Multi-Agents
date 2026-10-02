'use client';

import React, { useEffect, useState } from 'react';
import { Loader2, LogIn } from 'lucide-react';
import { fetchMe } from '../../lib/authClient';
import { t, useLang } from '../../lib/i18n';
import { apiFetch } from '../../lib/apiFetch';

export default function LoginPage() {
  const [lang, setLang] = useLang();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Already signed in (or the backend has no authentication at all): nothing to do here.
  useEffect(() => {
    fetchMe()
      .then((me) => {
        if (me) window.location.replace('/');
      })
      .catch(() => undefined);
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await apiFetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(typeof data.detail === 'string' ? data.detail : t(lang, 'login.failed', { status: response.status }));
        setPassword('');
        return;
      }
      window.location.replace('/');
    } catch {
      setError(t(lang, 'login.network'));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center px-4 bg-background">
      <form
        onSubmit={submit}
        className="w-full max-w-sm bg-surface border border-border rounded-2xl p-6 flex flex-col gap-4"
        aria-labelledby="login-title"
      >
        <div className="flex flex-col gap-1">
          <div className="flex items-start justify-between gap-2">
            <h1 id="login-title" className="text-lg font-semibold text-foreground">{t(lang, 'login.title')}</h1>
            <button
              type="button"
              onClick={() => setLang(lang === 'vi' ? 'en' : 'vi')}
              className="text-xs font-semibold text-foreground-secondary border border-border rounded-md px-2 py-0.5 hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
              aria-label={t(lang, 'lang.switch')}
              title={t(lang, 'lang.switch')}
            >
              {lang === 'vi' ? 'EN' : 'VI'}
            </button>
          </div>
          <p className="text-xs text-foreground-muted">Multi-Agent Enterprise System</p>
        </div>

        <label className="flex flex-col gap-1 text-xs font-medium text-foreground-secondary">
          {t(lang, 'login.username')}
          <input
            type="text"
            name="username"
            autoComplete="username"
            autoFocus
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="bg-surface-raised border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:border-accent-primary focus:ring-2 focus:ring-accent-primary/20"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs font-medium text-foreground-secondary">
          {t(lang, 'login.password')}
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="bg-surface-raised border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:border-accent-primary focus:ring-2 focus:ring-accent-primary/20"
          />
        </label>

        {error && (
          <p role="alert" className="text-xs text-accent-error">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={isSubmitting || !username.trim() || !password}
          className="flex items-center justify-center gap-2 bg-accent-primary hover:bg-accent-primary-hover text-white rounded-lg py-2 text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
        >
          {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
          {t(lang, 'login.submit')}
        </button>
      </form>
    </main>
  );
}
