'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Loader2, LogIn } from 'lucide-react';
import { fetchMe } from '../../lib/authClient';
import { t, useLang } from '../../lib/i18n';
import { apiFetch } from '../../lib/apiFetch';
import { Field, PRIMARY_BUTTON } from '../../components/auth/Field';
import { FptLogo } from '../../components/ui/FptLogo';

export default function LoginPage() {
  const [lang, setLang] = useLang();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const usernameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    usernameRef.current?.focus();
  }, []);

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
    <main className="min-h-dvh grid lg:grid-cols-[minmax(0,1fr)_minmax(0,32rem)] bg-background">
      {/* Identity column: wide screens only, the form column carries the logo on narrow ones */}
      <div className="hidden lg:flex flex-col justify-between border-r border-border bg-background-secondary p-12">
        <FptLogo className="h-8" />
        <div>
          <p className="text-4xl font-semibold tracking-tight text-foreground">
            FPT<span className="text-accent-primary">AgentHub</span>
          </p>
          <p className="mt-3 max-w-sm text-base text-foreground-secondary">{t(lang, 'login.tagline')}</p>
        </div>
        <span aria-hidden="true" />
      </div>

      <section className="flex min-w-0 flex-col px-6 py-6 sm:px-12">
        <div className="flex items-center justify-between gap-4">
          <div className="lg:hidden">
            <FptLogo className="h-7" />
          </div>
          <button
            type="button"
            onClick={() => setLang(lang === 'vi' ? 'en' : 'vi')}
            className="ml-auto min-h-8 whitespace-nowrap rounded-lg border border-border-strong px-3 text-xs font-semibold text-foreground-secondary hover:bg-surface-raised cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
            aria-label={t(lang, 'lang.switch')}
            title={t(lang, 'lang.switch')}
          >
            {lang === 'vi' ? 'EN' : 'VI'}
          </button>
        </div>

        <div className="flex w-full max-w-sm flex-1 flex-col justify-center py-10">
          <h1 id="login-title" className="text-2xl font-semibold tracking-tight text-foreground">
            {t(lang, 'login.title')}
          </h1>
          <p className="mt-1 text-sm text-foreground-secondary lg:hidden">{t(lang, 'login.tagline')}</p>

          <form onSubmit={submit} aria-labelledby="login-title" className="mt-8 flex flex-col gap-4">
            <Field
              id="login-username"
              label={t(lang, 'login.username')}
              value={username}
              onChange={setUsername}
              autoComplete="username"
              inputRef={usernameRef}
            />
            <Field
              id="login-password"
              type="password"
              label={t(lang, 'login.password')}
              value={password}
              onChange={setPassword}
              autoComplete="current-password"
            />

            {error && (
              <p role="alert" className="text-sm text-accent-error">
                {error}
              </p>
            )}

            <button type="submit" disabled={isSubmitting || !username.trim() || !password} className={PRIMARY_BUTTON}>
              {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <LogIn className="w-4 h-4" aria-hidden="true" />}
              {t(lang, 'login.submit')}
            </button>
          </form>
        </div>
      </section>
    </main>
  );
}
