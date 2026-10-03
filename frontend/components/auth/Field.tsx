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

/** A labelled text input with its error message, shared by the sign-in and change-password dialogs. */
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
