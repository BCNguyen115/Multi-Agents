/**
 * "The organization changed" for every admin page that shows tenants or departments: the page that changed it announces, the others (this tab
 * or another one) reload what they show. Without it a department created on one page was missing from the pickers of another until a refresh.
 */
const EVENT = 'admin:org-changed';
const KEY = 'admin:org-changed';

export function announceOrgChange(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new Event(EVENT));
  try {
    localStorage.setItem(KEY, String(Date.now())); // wakes the `storage` listeners of the OTHER tabs
  } catch {
    /* no storage (private window): this tab was told, the others catch up when they get the focus back */
  }
}

/** Calls `reload` when the organization changed anywhere, and when the tab becomes visible or focused again. Returns the unsubscribe function. */
export function onOrgChange(reload: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === KEY) reload();
  };
  const onVisible = () => {
    if (document.visibilityState === 'visible') reload();
  };
  window.addEventListener(EVENT, reload);
  window.addEventListener('storage', onStorage);
  window.addEventListener('focus', reload);
  document.addEventListener('visibilitychange', onVisible);
  return () => {
    window.removeEventListener(EVENT, reload);
    window.removeEventListener('storage', onStorage);
    window.removeEventListener('focus', reload);
    document.removeEventListener('visibilitychange', onVisible);
  };
}
