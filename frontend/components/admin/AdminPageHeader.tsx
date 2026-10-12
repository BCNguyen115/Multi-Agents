import React from 'react';

/** The one `h1` of an administration page, with what the page is for. */
export function AdminPageHeader({ title, description }: { title: string; description: string }) {
  return (
    <header className="space-y-1">
      <h1 className="text-2xl font-bold text-foreground">{title}</h1>
      <p className="max-w-3xl text-sm text-foreground-secondary">{description}</p>
    </header>
  );
}
