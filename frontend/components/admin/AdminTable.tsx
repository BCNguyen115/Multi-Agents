import React from 'react';

export interface Column<T> {
  key: string;
  /** Already translated: the page decides the words. */
  label: string;
  cell: (row: T) => React.ReactNode;
  numeric?: boolean;
  /** Extra classes for the cells of this column (`whitespace-nowrap`, a width...). */
  className?: string;
}

/**
 * The console's table: a bordered, horizontally scrolling box (`relative`, so an absolutely positioned cell cannot widen the page past it),
 * muted header cells, numbers right-aligned and tabular. `empty` replaces the table when there are no rows.
 */
export function AdminTable<T>({
  columns, rows, rowKey, empty, label,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  empty?: string;
  /** The name of the table for screen readers. */
  label?: string;
}) {
  if (rows.length === 0 && empty) return <p className="text-sm text-foreground-secondary">{empty}</p>;
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-xs" aria-label={label}>
        <thead className="bg-surface-raised text-foreground-muted">
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={`px-3 py-2 font-semibold ${c.numeric ? 'text-right' : ''}`}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row) => (
            <tr key={rowKey(row)} className="align-top hover:bg-surface-raised/50">
              {columns.map((c) => (
                <td key={c.key} className={`px-3 py-2 ${c.numeric ? 'text-right tabular-nums' : ''} ${c.className ?? ''}`}>{c.cell(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
