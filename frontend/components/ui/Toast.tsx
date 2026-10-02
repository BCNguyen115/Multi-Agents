'use client';

import React, { useState, useEffect } from 'react';
import { CheckCircle2, AlertCircle, Info, AlertTriangle, X } from 'lucide-react';
import { toast, ToastItem, ToastType } from '../../lib/toast';
import { t, useLang } from '../../lib/i18n';

const TOAST_ICONS: Record<ToastType, React.ReactNode> = {
  success: <CheckCircle2 className="w-4 h-4 text-accent-verifier shrink-0" />,
  error: <AlertCircle className="w-4 h-4 text-accent-error shrink-0" />,
  info: <Info className="w-4 h-4 text-accent-primary shrink-0" />,
  warning: <AlertTriangle className="w-4 h-4 text-foreground shrink-0" />,
};

const TOAST_ACCENTS: Record<ToastType, { border: string; bg: string; progress: string }> = {
  success: {
    border: 'border-accent-verifier/20',
    bg: 'bg-accent-verifier/5',
    progress: 'bg-accent-verifier',
  },
  error: {
    border: 'border-accent-error/20',
    bg: 'bg-accent-error/5',
    progress: 'bg-accent-error',
  },
  info: {
    border: 'border-accent-primary/20',
    bg: 'bg-accent-primary/5',
    progress: 'bg-accent-primary',
  },
  warning: {
    border: 'border-border-strong',
    bg: 'bg-surface-raised',
    progress: 'bg-foreground-secondary',
  },
};

export function ToastContainer() {
  const [lang] = useLang();
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  useEffect(() => {
    const unsubscribe = toast.subscribe((updated) => {
      setToasts(updated);
    });
    return unsubscribe;
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div
      aria-live="polite"
      className="fixed bottom-5 right-5 z-[9999] flex flex-col gap-2.5 max-w-sm w-full pointer-events-none select-none"
    >
      {toasts.map((item) => {
        const accent = TOAST_ACCENTS[item.type] || TOAST_ACCENTS.info;
        const duration = item.duration ?? 3500;

        return (
          <div
            key={item.id}
            role="status"
            className={`pointer-events-auto relative overflow-hidden rounded-xl border ${accent.border} bg-surface shadow-lg p-3.5 flex flex-col gap-1.5 animate-fade-in transition-all duration-200`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-start gap-2.5 flex-1 min-w-0">
                <div className="mt-0.5">{TOAST_ICONS[item.type]}</div>
                <div className="flex-1 min-w-0">
                  {item.title && (
                    <p className="text-xs font-semibold text-foreground tracking-tight mb-0.5">
                      {item.title}
                    </p>
                  )}
                  <p className="text-xs text-foreground-secondary leading-snug break-words">
                    {item.message}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-1 shrink-0">
                {item.action && (
                  <button
                    type="button"
                    onClick={() => {
                      item.action?.onClick();
                      toast.dismiss(item.id);
                    }}
                    className="px-2 py-1 text-2xs font-semibold bg-surface-raised hover:bg-surface-overlay border border-border text-foreground rounded-md transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-primary"
                  >
                    {item.action.label}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => toast.dismiss(item.id)}
                  className="p-1 text-foreground-muted hover:text-foreground rounded-md hover:bg-surface-raised transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-primary"
                  aria-label={t(lang, 'toast.close')}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Bottom Progress Bar */}
            {duration > 0 && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-border/40 overflow-hidden">
                <div
                  className={`h-full ${accent.progress}`}
                  style={{
                    animation: `toast-progress ${duration}ms linear forwards`,
                  }}
                />
              </div>
            )}
          </div>
        );
      })}

      <style jsx global>{`
        @keyframes toast-progress {
          from {
            width: 100%;
          }
          to {
            width: 0%;
          }
        }
      `}</style>
    </div>
  );
}
