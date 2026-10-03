'use client';

import { useEffect, type RefObject } from 'react';

const FOCUSABLE = 'button, input, [href], [tabindex]:not([tabindex="-1"])';

/**
 * What a modal dialog owes the keyboard: Escape closes it (when `canClose`), Tab stays inside it, and closing hands the
 * focus back to whatever opened it.
 */
export function useDialogA11y(open: boolean, dialogRef: RefObject<HTMLElement | null>, onClose: () => void, canClose = true): void {
  useEffect(() => {
    if (!open) return undefined;
    const opener = document.activeElement as HTMLElement | null;
    return () => opener?.focus?.();
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && canClose) {
        onClose();
      } else if (event.key === 'Tab' && dialogRef.current) {
        const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => !el.hasAttribute('disabled'));
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
  }, [open, canClose, onClose, dialogRef]);
}
