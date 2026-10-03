'use client';

import { useSyncExternalStore } from 'react';

// One MutationObserver on <html> for the whole page, however many charts and grids ask "is it dark?"
const listeners = new Set<() => void>();
let observer: MutationObserver | null = null;

const read = () =>
  document.documentElement.classList.contains('dark') || document.documentElement.getAttribute('data-theme') === 'dark';

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  if (!observer) {
    observer = new MutationObserver(() => listeners.forEach((l) => l()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] });
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      observer?.disconnect();
      observer = null;
    }
  };
}

/** True while the dark theme is on (dark is also what the server renders, so the first paint matches). */
export function useIsDark(): boolean {
  return useSyncExternalStore(subscribe, read, () => true);
}
