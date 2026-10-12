'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Load something for an admin page and keep it: `reload()` asks again, a new `fetcher` (wrap it in `useCallback` with the filters it
 * reads) asks again by itself, and `refreshMs` re-asks while the tab is visible. The older of two overlapping answers is dropped, and what
 * is already on screen stays until the new answer arrives, so a filter change does not blank the table.
 */
export function useAdminData<T>(fetcher: () => Promise<T>, refreshMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const latest = useRef(0);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    const mine = ++latest.current;
    setBusy(true);
    try {
      const next = await fetcher();
      if (alive.current && mine === latest.current) {
        setData(next);
        setError(null);
      }
    } catch (e: unknown) {
      if (alive.current && mine === latest.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (alive.current && mine === latest.current) setBusy(false);
    }
  }, [fetcher]);

  useEffect(() => {
    void reload();
    if (!refreshMs) return undefined;
    const tick = () => {
      if (document.visibilityState === 'visible') void reload(); // a hidden tab asks nothing; coming back asks at once
    };
    const timer = window.setInterval(tick, refreshMs);
    document.addEventListener('visibilitychange', tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [reload, refreshMs]);

  return { data, error, busy, reload, setData };
}
