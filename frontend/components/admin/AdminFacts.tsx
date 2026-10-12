import React from 'react';

const COLUMNS: Record<number, string> = { 3: 'lg:grid-cols-3', 4: 'lg:grid-cols-4', 5: 'lg:grid-cols-5' };

/** Label/value cells in one bordered strip. The columns follow the number of cells and a lone last cell on the two-column row stretches, so no empty grey cell shows the hairline background. */
export function AdminFacts({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className={`grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 ${COLUMNS[rows.length] ?? 'lg:grid-cols-4'}`}>
      {rows.map(([label, value]) => (
        <div key={label} className="bg-surface p-3 sm:[&:last-child:nth-child(odd)]:col-span-2 lg:[&:last-child:nth-child(odd)]:col-span-1">
          <dt className="text-xs text-foreground-muted">{label}</dt>
          <dd className="mt-1 break-words text-sm font-semibold tabular-nums text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
