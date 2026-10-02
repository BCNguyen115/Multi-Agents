'use client';

import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, Copy, Loader2, X } from 'lucide-react';
import { useAuth, type AuthTab } from '../../context/AuthContext';
import { t, useLang, type MessageKey } from '../../lib/i18n';

// The same rules the backend enforces (RegisterRequest): checking them here only saves a round trip.
const USERNAME_RULE = /^[A-Za-z0-9._-]{3,32}$/;
const MIN_PASSWORD = 10;

type View = 'form' | 'forgot' | 'recovery';

interface FieldProps {
  id: string;
  label: string;
  type?: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  autoComplete: string;
  inputRef?: React.Ref<HTMLInputElement>;
}

function Field({ id, label, type = 'text', value, onChange, error, autoComplete, inputRef }: FieldProps) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-foreground-secondary">
        {label}
      </label>
      <input
        id={id}
        ref={inputRef}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`w-full rounded-xl bg-background border px-3.5 py-2.5 text-sm text-foreground placeholder:text-foreground-muted transition-colors focus:outline-none focus:ring-2 ${
          error ? 'border-accent-error focus:ring-accent-error/30' : 'border-border-strong focus:border-accent-primary focus:ring-accent-primary/30'
        }`}
      />
      {error && (
        <p id={`${id}-error`} className="text-xs text-accent-error">
          {error}
        </p>
      )}
    </div>
  );
}

const PRIMARY_BUTTON =
  'flex w-full min-h-11 items-center justify-center gap-2 rounded-xl bg-accent-primary px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-primary-hover disabled:opacity-60 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface';
const LINK_BUTTON =
  'text-sm font-medium text-accent-primary hover:underline cursor-pointer rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40';

/** Sign-in / sign-up / forgot-password dialog. Opens from the settings menu, and by itself when the session is missing or has expired. */
export function AuthModal() {
  const [lang] = useLang();
  const { authModal, closeAuthModal, config, login, register, resetPassword, finishSignIn } = useAuth();
  const [tab, setTab] = useState<AuthTab>('signin');
  const [view, setView] = useState<View>('form');
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [keyInput, setKeyInput] = useState('');
  const [issuedKey, setIssuedKey] = useState('');
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState('');
  const [busy, setBusy] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFieldRef = useRef<HTMLInputElement>(null);

  // The recovery key is shown once: until it has been acknowledged the dialog cannot be dismissed.
  const locked = view === 'recovery';

  // Every time the dialog opens, or the tab/view changes, start from a clean form.
  useEffect(() => {
    if (!authModal.open) return;
    setTab(authModal.tab);
    setView('form');
  }, [authModal]);

  useEffect(() => {
    if (!authModal.open) return;
    setErrors({});
    setFormError('');
    setPassword('');
    setConfirm('');
    setKeyInput('');
    firstFieldRef.current?.focus();
  }, [authModal.open, tab, view]);

  // Escape closes (unless locked); Tab stays inside the dialog.
  useEffect(() => {
    if (!authModal.open) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy && !locked) {
        closeAuthModal();
      } else if (event.key === 'Tab' && dialogRef.current) {
        const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button, input, [href], [tabindex]:not([tabindex="-1"])')).filter((el) => !el.hasAttribute('disabled'));
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [authModal.open, busy, locked, closeAuthModal]);

  if (!authModal.open || typeof document === 'undefined') return null;

  const signUp = tab === 'signup';
  const forgot = view === 'forgot';

  const validate = (): Record<string, string> => {
    const found: Record<string, string> = {};
    if (forgot) {
      if (!username.trim()) found.username = t(lang, 'auth.err.required');
      if (!keyInput.trim()) found.key = t(lang, 'auth.err.keyRequired');
      if (password.length < MIN_PASSWORD) found.password = t(lang, 'auth.err.passwordShort');
      if (confirm !== password) found.confirm = t(lang, 'auth.err.mismatch');
      return found;
    }
    if (!username.trim() || !password) {
      if (!username.trim()) found.username = t(lang, 'auth.err.required');
      if (!password) found.password = t(lang, 'auth.err.required');
      return found;
    }
    if (signUp) {
      if (!USERNAME_RULE.test(username.trim())) found.username = t(lang, 'auth.err.usernameFormat');
      if (password.length < MIN_PASSWORD) found.password = t(lang, 'auth.err.passwordShort');
      if (confirm !== password) found.confirm = t(lang, 'auth.err.mismatch');
    }
    return found;
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const found = validate();
    setErrors(found);
    setFormError('');
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      if (forgot) {
        const { recoveryKey } = await resetPassword({ username: username.trim(), recoveryKey: keyInput.trim(), newPassword: password });
        showKey(recoveryKey);
      } else if (signUp) {
        const { recoveryKey } = await register({ username: username.trim(), password, displayName: displayName.trim() });
        showKey(recoveryKey);
      } else {
        await login(username.trim(), password); // success reloads the page with the new session
      }
    } catch (error) {
      setFormError(error instanceof Error && error.message ? error.message : t(lang, 'auth.err.generic'));
      setBusy(false);
    }
  };

  const showKey = (key: string) => {
    setIssuedKey(key);
    setSaved(false);
    setCopied(false);
    setBusy(false);
    setView('recovery');
  };

  const copyKey = async () => {
    try {
      await navigator.clipboard.writeText(issuedKey);
      setCopied(true);
    } catch {
      /* the key stays selectable on screen */
    }
  };

  const tabButton = (id: AuthTab, label: MessageKey) => (
    <button
      type="button"
      role="tab"
      id={`auth-tab-${id}`}
      aria-selected={tab === id}
      aria-controls="auth-panel"
      onClick={() => setTab(id)}
      className={`flex-1 rounded-full px-4 py-2 text-sm font-medium transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40 ${
        tab === id ? 'bg-surface-raised text-foreground' : 'text-foreground-secondary hover:text-foreground'
      }`}
    >
      {t(lang, label)}
    </button>
  );

  const title: MessageKey = locked ? 'auth.recovery.title' : forgot ? 'auth.forgot.title' : signUp ? 'auth.title.signUp' : 'auth.title.signIn';

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-background/60 backdrop-blur-sm" data-testid="auth-modal">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-title"
        className="relative w-full max-w-md max-h-[calc(100vh-2rem)] overflow-y-auto rounded-2xl border border-border-strong bg-surface p-6 shadow-lg animate-fade-in-scale"
      >
        {!locked && (
          <button
            type="button"
            onClick={closeAuthModal}
            disabled={busy}
            aria-label={t(lang, 'auth.close')}
            className="absolute right-3 top-3 w-9 h-9 rounded-full flex items-center justify-center text-foreground-secondary hover:text-foreground hover:bg-surface-raised transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
          >
            <X className="w-[18px] h-[18px]" aria-hidden="true" />
          </button>
        )}

        <h2 id="auth-title" className="pr-10 text-xl font-semibold text-foreground">
          {t(lang, title)}
        </h2>

        {view === 'form' && (
          <div role="tablist" aria-label={t(lang, 'auth.tabs')} className="mt-4 flex gap-1 rounded-full border border-border bg-background p-1">
            {tabButton('signin', 'auth.tab.signIn')}
            {tabButton('signup', 'auth.tab.signUp')}
          </div>
        )}

        <div id="auth-panel" role={view === 'form' ? 'tabpanel' : undefined} aria-labelledby={view === 'form' ? `auth-tab-${tab}` : undefined} className="mt-5">
          {view === 'recovery' ? (
            <div className="space-y-4">
              <p className="text-sm text-foreground-secondary">{t(lang, 'auth.recovery.body')}</p>
              <div className="flex items-center gap-2 rounded-xl border border-border-strong bg-background p-3">
                <code className="flex-1 select-all break-all font-mono text-sm tabular-nums text-foreground" data-testid="recovery-key">
                  {issuedKey}
                </code>
                <button
                  type="button"
                  onClick={copyKey}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-raised hover:text-foreground cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-accent-primary" aria-hidden="true" /> : <Copy className="w-3.5 h-3.5" aria-hidden="true" />}
                  {copied ? t(lang, 'auth.recovery.copied') : t(lang, 'auth.recovery.copy')}
                </button>
              </div>
              <label className="flex items-start gap-2.5 text-sm text-foreground cursor-pointer">
                <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[var(--accent-primary)]" />
                <span>{t(lang, 'auth.recovery.saved')}</span>
              </label>
              <button type="button" disabled={!saved} onClick={finishSignIn} className={PRIMARY_BUTTON}>
                {t(lang, 'auth.recovery.continue')}
              </button>
            </div>
          ) : !config.login_enabled ? (
            <p role="status" className="text-sm text-foreground-secondary">{t(lang, 'auth.loginUnavailable')}</p>
          ) : forgot ? (
            !config.registration_enabled ? (
              <div className="space-y-4">
                <p role="status" className="text-sm text-foreground-secondary">{t(lang, 'auth.forgot.managed')}</p>
                <button type="button" onClick={() => setView('form')} className={LINK_BUTTON}>{t(lang, 'auth.backToSignIn')}</button>
              </div>
            ) : (
              <form onSubmit={submit} noValidate className="space-y-4">
                <p className="text-sm text-foreground-secondary">{t(lang, 'auth.forgot.hint')}</p>
                <Field id="auth-username" label={t(lang, 'auth.username')} value={username} onChange={setUsername} error={errors.username} autoComplete="username" inputRef={firstFieldRef} />
                <Field id="auth-key" label={t(lang, 'auth.recoveryKey')} value={keyInput} onChange={setKeyInput} error={errors.key} autoComplete="off" />
                <Field id="auth-password" label={t(lang, 'auth.newPassword')} type="password" value={password} onChange={setPassword} error={errors.password} autoComplete="new-password" />
                <Field id="auth-confirm" label={t(lang, 'auth.confirm')} type="password" value={confirm} onChange={setConfirm} error={errors.confirm} autoComplete="new-password" />
                {formError && (
                  <p role="alert" className="rounded-xl border border-accent-error/30 bg-accent-error/10 px-3.5 py-2.5 text-sm text-accent-error">{formError}</p>
                )}
                <button type="submit" disabled={busy} className={PRIMARY_BUTTON}>
                  {busy && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
                  {busy ? t(lang, 'auth.working') : t(lang, 'auth.submit.reset')}
                </button>
                <button type="button" onClick={() => setView('form')} className={LINK_BUTTON}>{t(lang, 'auth.backToSignIn')}</button>
              </form>
            )
          ) : signUp && !config.registration_enabled ? (
            <p role="status" className="text-sm text-foreground-secondary">{t(lang, 'auth.registerClosed')}</p>
          ) : (
            <form onSubmit={submit} noValidate className="space-y-4">
              <Field id="auth-username" label={t(lang, 'auth.username')} value={username} onChange={setUsername} error={errors.username} autoComplete="username" inputRef={firstFieldRef} />
              {signUp && <Field id="auth-display-name" label={t(lang, 'auth.displayName')} value={displayName} onChange={setDisplayName} autoComplete="name" />}
              <Field id="auth-password" label={t(lang, 'auth.password')} type="password" value={password} onChange={setPassword} error={errors.password} autoComplete={signUp ? 'new-password' : 'current-password'} />
              {signUp && <Field id="auth-confirm" label={t(lang, 'auth.confirm')} type="password" value={confirm} onChange={setConfirm} error={errors.confirm} autoComplete="new-password" />}

              {formError && (
                <p role="alert" className="rounded-xl border border-accent-error/30 bg-accent-error/10 px-3.5 py-2.5 text-sm text-accent-error">
                  {formError}
                </p>
              )}

              <button type="submit" disabled={busy} className={PRIMARY_BUTTON}>
                {busy && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
                {busy ? t(lang, 'auth.working') : t(lang, signUp ? 'auth.submit.signUp' : 'auth.submit.signIn')}
              </button>
              {!signUp && config.registration_enabled && (
                <button type="button" onClick={() => setView('forgot')} className={LINK_BUTTON}>
                  {t(lang, 'auth.forgot')}
                </button>
              )}
            </form>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
