'use client';

import { useCallback, useEffect, useRef } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import {
  ConflictError,
  clearLocalConversations,
  conflictCopy,
  deleteRemote,
  fingerprint,
  getRemote,
  isBusy,
  listRemote,
  loadSyncState,
  planSync,
  putRemote,
  saveSyncState,
  SYNC_OWNER_KEY,
  type RemoteConversation,
  type SyncedSession,
  type SyncState,
} from './conversationSync';
import { STORAGE_MESSAGES_KEY, STORAGE_SESSIONS_KEY } from './storage';
import { toast } from './toast';
import type { ChatMessage } from './types';
import { getLang, t } from './i18n';

const PUSH_DELAY_MS = 2_000;
const POLL_MS = 60_000;
const FOCUS_THROTTLE_MS = 15_000;

interface Options {
  /** Sync only for a signed-in user: without authentication every browser would share one server-side user. */
  enabled: boolean;
  userId: string | null;
  /** The local copy has been loaded from localStorage. */
  ready: boolean;
  sessions: SyncedSession[];
  messagesMap: Record<string, ChatMessage[]>;
  setSessions: Dispatch<SetStateAction<SyncedSession[]>>;
  setMessagesMap: Dispatch<SetStateAction<Record<string, ChatMessage[]>>>;
  /** Another user signed in on this browser: the previous user's local chats were cleared, start from a blank state. */
  onOwnerChanged: () => void;
}

const asSession = (c: RemoteConversation): SyncedSession => ({ id: c.id, title: c.title, isPinned: c.pinned, updatedAt: c.updated_at });

export function useConversationSync(options: Options): void {
  const latest = useRef(options);
  latest.current = options;
  const state = useRef<SyncState>({});
  const running = useRef(false);
  const again = useRef(false);
  const lastFocusRun = useRef(0);

  const applyServer = useCallback((server: RemoteConversation) => {
    const { setSessions, setMessagesMap } = latest.current;
    const incoming = asSession(server);
    setSessions((prev) => (prev.some((s) => s.id === server.id) ? prev.map((s) => (s.id === server.id ? incoming : s)) : [incoming, ...prev]));
    setMessagesMap((prev) => ({ ...prev, [server.id]: server.messages }));
    state.current[server.id] = { version: server.updated_at, hash: fingerprint(incoming, server.messages) };
  }, []);

  /** The server's version wins; what this browser had is kept as a separate conversation (uploaded by the next round). */
  const resolveConflict = useCallback(
    (id: string, server: RemoteConversation) => {
      const { sessions, messagesMap, setSessions, setMessagesMap } = latest.current;
      const mine = sessions.find((s) => s.id === id);
      if (mine) {
        const copy = conflictCopy(mine, messagesMap[id] ?? []);
        setSessions((prev) => [copy.session, ...prev]);
        setMessagesMap((prev) => ({ ...prev, [copy.session.id]: copy.messages }));
        toast.warning(t(getLang(), 'sync.conflict', { title: mine.title }), { title: t(getLang(), 'sync.title') });
      }
      applyServer(server);
    },
    [applyServer],
  );

  const syncOnce = useCallback(async () => {
    const { sessions, messagesMap, setSessions, setMessagesMap } = latest.current;
    const remote = await listRemote();
    const views = sessions.map((s) => {
      const messages = messagesMap[s.id] ?? [];
      return { id: s.id, hash: fingerprint(s, messages), busy: isBusy(messages) };
    });
    const plan = planSync(views, remote, state.current);

    for (const id of plan.pull) applyServer(await getRemote(id));
    for (const id of plan.conflicts) resolveConflict(id, await getRemote(id));

    for (const id of plan.push) {
      const session = sessions.find((s) => s.id === id);
      if (!session) continue;
      const messages = messagesMap[id] ?? [];
      try {
        const saved = await putRemote(session, messages, state.current[id]?.version ?? null);
        state.current[id] = { version: saved.updated_at, hash: fingerprint(session, messages) };
      } catch (error) {
        if (error instanceof ConflictError) resolveConflict(id, error.server);
        else console.warn(`Could not save conversation ${id}`, error);
      }
    }

    for (const id of plan.deleteRemote) {
      await deleteRemote(id);
      delete state.current[id];
    }
    if (plan.deleteLocal.length) {
      const gone = new Set(plan.deleteLocal);
      setSessions((prev) => prev.filter((s) => !gone.has(s.id)));
      setMessagesMap((prev) => Object.fromEntries(Object.entries(prev).filter(([id]) => !gone.has(id))));
      plan.deleteLocal.forEach((id) => delete state.current[id]);
    }

    const alive = new Set([...sessions.map((s) => s.id), ...remote.map((r) => r.id)]);
    Object.keys(state.current).filter((id) => !alive.has(id)).forEach((id) => delete state.current[id]);
    saveSyncState(state.current);
  }, [applyServer, resolveConflict]);

  const run = useCallback(async () => {
    if (running.current) {
      again.current = true;
      return;
    }
    running.current = true;
    try {
      do {
        again.current = false;
        await syncOnce();
      } while (again.current);
    } catch (error) {
      console.warn('Conversation sync failed, will retry', error); // offline or signed out: the local copy keeps working
    } finally {
      running.current = false;
    }
  }, [syncOnce]);

  // Start (and, when another user signs in on this browser, start clean).
  const { enabled, ready, userId } = options;
  useEffect(() => {
    if (!enabled || !ready || !userId) return;
    let owner: string | null = null;
    try {
      owner = localStorage.getItem(SYNC_OWNER_KEY);
      localStorage.setItem(SYNC_OWNER_KEY, userId);
    } catch {
      /* storage blocked: sync still works for this page view */
    }
    if (owner && owner !== userId) {
      clearLocalConversations([STORAGE_SESSIONS_KEY, STORAGE_MESSAGES_KEY]);
      state.current = {};
      latest.current.onOwnerChanged(); // the reset re-renders and this effect's data effect below starts the first sync
      return;
    }
    state.current = loadSyncState();
    void run();
  }, [enabled, ready, userId, run]);

  // Save changes shortly after the last edit (a reply that is still streaming is skipped by the plan).
  const { sessions, messagesMap } = options;
  useEffect(() => {
    if (!enabled || !ready) return;
    const timer = setTimeout(() => void run(), PUSH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [enabled, ready, sessions, messagesMap, run]);

  // Pick up what happened on other devices: when this tab regains focus, and once a minute.
  useEffect(() => {
    if (!enabled || !ready) return;
    const onFocus = () => {
      if (document.visibilityState === 'visible' && Date.now() - lastFocusRun.current > FOCUS_THROTTLE_MS) {
        lastFocusRun.current = Date.now();
        void run();
      }
    };
    document.addEventListener('visibilitychange', onFocus);
    window.addEventListener('focus', onFocus);
    const poll = setInterval(() => void run(), POLL_MS);
    return () => {
      document.removeEventListener('visibilitychange', onFocus);
      window.removeEventListener('focus', onFocus);
      clearInterval(poll);
    };
  }, [enabled, ready, run]);
}
