import React from 'react';
import Link from 'next/link';

interface AdminStatProps {
  label: string;
  value: React.ReactNode;
  hint?: string;
  /** Where the number is dealt with; the whole card is then the link. */
  href?: string;
  /** `alert` is rose, the colour of errors: use it only for something that has gone wrong. */
  tone?: 'neutral' | 'alert';
}

const CARD = 'block min-h-[112px] rounded-lg border border-border bg-surface p-4';

/** One number an administrator compares at a glance (tabular figures, label above, a line of context below). */
export function AdminStat({ label, value, hint, href, tone = 'neutral' }: AdminStatProps) {
  const body = (
    <>
      <p className="text-xs font-semibold text-foreground-muted">{label}</p>
      <p className={`mt-1 text-2xl font-bold tabular-nums ${tone === 'alert' ? 'text-accent-error' : 'text-foreground'}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-foreground-muted">{hint}</p>}
    </>
  );
  if (!href) return <div className={CARD}>{body}</div>;
  return (
    <Link href={href} className={`${CARD} transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary`}>
      {body}
    </Link>
  );
}
