'use client';

import React, { useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Loader2, X } from 'lucide-react';
import { t, useLang } from '../../lib/i18n';
import { useDialogA11y } from '../../lib/useDialogA11y';

/** A modal for the console: Escape closes it, Tab stays inside, closing hands the focus back (the same rules as the sign-in dialogs). */
export function AdminDialog({
  open, title, onClose, canClose = true, children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  /** False while something is being saved: the dialog may not be dismissed halfway. */
  canClose?: boolean;
  children: React.ReactNode;
}) {
  const [lang] = useLang();
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogA11y(open, dialogRef, onClose, canClose);
  if (!open || typeof document === 'undefined') return null;
  return createPortal(
    <div className="fixed inset-0 z-modal flex items-center justify-center bg-background/60 p-4 backdrop-blur-sm">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative max-h-[calc(100dvh-2rem)] w-full max-w-md overflow-y-auto rounded-2xl border border-border-strong bg-surface p-6 shadow-lg animate-fade-in-scale"
      >
        <button
          type="button"
          onClick={onClose}
          disabled={!canClose}
          aria-label={t(lang, 'admin.dialog.close')}
          className="absolute right-3 top-3 flex h-9 w-9 cursor-pointer items-center justify-center rounded-full text-foreground-secondary transition-colors hover:bg-surface-raised hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary disabled:opacity-50"
        >
          <X className="h-[18px] w-[18px]" aria-hidden="true" />
        </button>
        <h2 id={titleId} className="pr-10 text-lg font-semibold text-foreground">{title}</h2>
        <div className="mt-4">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

/** "Are you sure?" for a change that is hard to take back. The focus starts on Cancel: Enter does not confirm by accident. */
export function ConfirmDialog({
  open, title, body, confirmLabel, danger = false, busy = false, onConfirm, onCancel,
}: {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [lang] = useLang();
  return (
    <AdminDialog open={open} title={title} onClose={onCancel} canClose={!busy}>
      <p className="text-sm text-foreground-secondary">{body}</p>
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" className="btn-dash" onClick={onCancel} disabled={busy} autoFocus>
          {t(lang, 'admin.dialog.cancel')}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className={danger ? 'btn-dash border-accent-error/50 text-accent-error' : 'btn-primary'}
        >
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          {confirmLabel}
        </button>
      </div>
    </AdminDialog>
  );
}
