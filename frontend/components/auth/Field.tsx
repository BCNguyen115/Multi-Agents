import React from 'react';

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

/** The one primary button of every sign-in surface (the /login page, the sign-in dialog, change password). */
export const PRIMARY_BUTTON =
  'flex w-full min-h-11 items-center justify-center gap-2 rounded-xl bg-accent-fill px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-fill-hover disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface';

/** A labelled text input with its error message, shared by the sign-in and change-password dialogs and the /login page. */
export function Field({ id, label, type = 'text', value, onChange, error, autoComplete, inputRef }: FieldProps) {
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
        className={`w-full rounded-xl bg-background border px-3.5 py-2.5 text-base sm:text-sm text-foreground placeholder:text-foreground-muted transition-colors focus:outline-none focus:ring-2 ${
          error ? 'border-accent-error focus:ring-accent-error' : 'border-border-input focus:border-accent-primary focus:ring-accent-primary'
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
