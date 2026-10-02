'use client';

import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle2, Loader2, X } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { t, useLang } from '../../lib/i18n';

const MIN_PASSWORD = 10;

function PasswordField({ id, label, value, onChange, error, autoComplete, inputRef }: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  autoComplete: string;
  inputRef?: React.Ref<HTMLInputElement>;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-foreground-secondary">{label}</label>
      <input
        id={id}
        ref={inputRef}
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={`w-full rounded-xl bg-background border px-3.5 py-2.5 text-sm text-foreground transition-colors focus:outline-none focus:ring-2 ${
          error ? 'border-accent-error focus:ring-accent-error/30' : 'border-border-strong focus:border-accent-primary focus:ring-accent-primary/30'
        }`}
      />
      {error && <p id={`${id}-error`} className="text-xs text-accent-error">{error}</p>}
    </div>
  );
}

/** Change the signed-in user's password: the current one is the proof. Opened from the settings menu. */
export function ChangePasswordDialog() {
  const [lang] = useLang();
  const { changePasswordOpen, closeChangePassword, changePassword } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const firstFieldRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!changePasswordOpen) return;
    setCurrent('');
    setNext('');
    setConfirm('');
    setErrors({});
    setFormError('');
    setDone(false);
    setBusy(false);
    firstFieldRef.current?.focus();
  }, [changePasswordOpen]);

  useEffect(() => {
    if (!changePasswordOpen) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) {
        closeChangePassword();
      } else if (event.key === 'Tab' && dialogRef.current) {
        const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>('button, input')).filter((el) => !el.hasAttribute('disabled'));
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
  }, [changePasswordOpen, busy, closeChangePassword]);

  if (!changePasswordOpen || typeof document === 'undefined') return null;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    const found: Record<string, string> = {};
    if (!current) found.current = t(lang, 'auth.err.required');
    if (next.length < MIN_PASSWORD) found.next = t(lang, 'auth.err.passwordShort');
    if (confirm !== next) found.confirm = t(lang, 'auth.err.mismatch');
    setErrors(found);
    setFormError('');
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      await changePassword(current, next);
      setDone(true);
    } catch (error) {
      setFormError(error instanceof Error && error.message ? error.message : t(lang, 'auth.err.generic'));
    } finally {
      setBusy(false);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-background/60 backdrop-blur-sm" data-testid="change-password-dialog">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="pwd-title"
        className="relative w-full max-w-md max-h-[calc(100vh-2rem)] overflow-y-auto rounded-2xl border border-border-strong bg-surface p-6 shadow-lg animate-fade-in-scale"
      >
        <button
          type="button"
          onClick={closeChangePassword}
          disabled={busy}
          aria-label={t(lang, 'auth.close')}
          className="absolute right-3 top-3 w-9 h-9 rounded-full flex items-center justify-center text-foreground-secondary hover:text-foreground hover:bg-surface-raised transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
        >
          <X className="w-[18px] h-[18px]" aria-hidden="true" />
        </button>
        <h2 id="pwd-title" className="pr-10 text-xl font-semibold text-foreground">{t(lang, 'pwd.title')}</h2>

        {done ? (
          <div className="mt-5 space-y-4">
            <p role="status" className="flex items-center gap-2 text-sm font-medium text-foreground">
              <CheckCircle2 className="w-5 h-5 text-accent-verifier" aria-hidden="true" />
              {t(lang, 'pwd.done')}
            </p>
            <p className="text-sm text-foreground-secondary">{t(lang, 'pwd.doneNote')}</p>
            <button
              type="button"
              onClick={closeChangePassword}
              className="flex w-full min-h-11 items-center justify-center rounded-xl bg-accent-primary px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-primary-hover cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
            >
              {t(lang, 'auth.close')}
            </button>
          </div>
        ) : (
          <form onSubmit={submit} noValidate className="mt-5 space-y-4">
            <PasswordField id="pwd-current" label={t(lang, 'pwd.current')} value={current} onChange={setCurrent} error={errors.current} autoComplete="current-password" inputRef={firstFieldRef} />
            <PasswordField id="pwd-new" label={t(lang, 'pwd.new')} value={next} onChange={setNext} error={errors.next} autoComplete="new-password" />
            <PasswordField id="pwd-confirm" label={t(lang, 'pwd.confirm')} value={confirm} onChange={setConfirm} error={errors.confirm} autoComplete="new-password" />
            {formError && (
              <p role="alert" className="rounded-xl border border-accent-error/30 bg-accent-error/10 px-3.5 py-2.5 text-sm text-accent-error">{formError}</p>
            )}
            <button
              type="submit"
              disabled={busy}
              className="flex w-full min-h-11 items-center justify-center gap-2 rounded-xl bg-accent-primary px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-primary-hover disabled:opacity-60 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-surface"
            >
              {busy && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
              {busy ? t(lang, 'auth.working') : t(lang, 'pwd.submit')}
            </button>
          </form>
        )}
      </div>
    </div>,
    document.body
  );
}
