/**
 * Keeping the browser's conversations and the server's (`/api/conversations`) in step, for a signed-in user.
 *
 * The browser still works from its own copy (localStorage); the server is the shared, durable one. For every conversation
 * we remember what we last agreed on (`SyncState`: the server's version string and a fingerprint of the content). Comparing
 * that with the two sides tells who changed what since:
 *
 *   only we changed it        -> push        only the server changed it  -> pull
 *   both changed it           -> conflict: the server's version wins, ours is kept as a separate copy (nothing is lost)
 *   gone on one side          -> deleted there: delete here too (unless we have unsaved edits: then it is pushed again)
 *
 * `planSync` is pure so these rules can be tested without a browser or a server.
 */

import { sanitizeMessagesForStorage } from './storage';
import { isUnauthorized } from './authClient';
import type { ChatMessage } from './types';
import { getLang, t } from './i18n';
import { apiFetch } from './apiFetch';

export interface SyncedSession {
  id: string;
  title: string;
  isPinned: boolean;
  updatedAt: string;
}

export interface RemoteSummary {
  id: string;
  title: string;
  pinned: boolean;
  /** Opaque version string: send it back unchanged as `base_updated_at`. */
  updated_at: string;
}

export interface RemoteConversation extends RemoteSummary {
  messages: ChatMessage[];
}

export interface SyncEntry {
  version: string;
  hash: string;
}
export type SyncState = Record<string, SyncEntry>;

export interface LocalView {
  id: string;
  hash: string;
  /** A reply is still being written: never save a half-finished conversation. */
  busy: boolean;
}

export interface SyncPlan {
  pull: string[];
  push: string[];
  deleteRemote: string[];
  deleteLocal: string[];
  conflicts: string[];
}

export const SYNC_STATE_KEY = 'fpt_chat_sync_state';
export const SYNC_OWNER_KEY = 'fpt_chat_owner';

/** Small, stable fingerprint (32-bit djb2) of what a sync cares about. Not a security hash. */
export function fingerprint(session: Pick<SyncedSession, 'title' | 'isPinned'>, messages: ChatMessage[]): string {
  const text = JSON.stringify([session.title, session.isPinned, messages]);
  let hash = 5381;
  for (let i = 0; i < text.length; i++) {
    hash = ((hash << 5) + hash + text.charCodeAt(i)) | 0;
  }
  return (hash >>> 0).toString(16) + ':' + text.length;
}

export function isBusy(messages: ChatMessage[]): boolean {
  return messages.some((m) => m.status === 'loading');
}

export function planSync(local: LocalView[], remote: RemoteSummary[], state: SyncState): SyncPlan {
  const plan: SyncPlan = { pull: [], push: [], deleteRemote: [], deleteLocal: [], conflicts: [] };
  const localById = new Map(local.map((l) => [l.id, l]));
  const remoteById = new Map(remote.map((r) => [r.id, r]));

  for (const id of new Set([...localById.keys(), ...remoteById.keys(), ...Object.keys(state)])) {
    const mine = localById.get(id);
    const theirs = remoteById.get(id);
    const known = state[id];

    if (mine && theirs) {
      if (!known) plan.conflicts.push(id); // two histories that never met
      else if (theirs.updated_at === known.version) {
        if (mine.hash !== known.hash && !mine.busy) plan.push.push(id);
      } else if (mine.hash === known.hash) plan.pull.push(id);
      else plan.conflicts.push(id);
    } else if (mine) {
      if (known && mine.hash === known.hash) plan.deleteLocal.push(id); // deleted on another device, nothing unsaved here
      else if (!mine.busy) plan.push.push(id);
    } else if (theirs) {
      if (known) plan.deleteRemote.push(id); // we deleted it here
      else plan.pull.push(id);
    }
    // neither side has it: the stale state entry is dropped by the caller
  }
  return plan;
}

export function loadSyncState(): SyncState {
  try {
    const raw = localStorage.getItem(SYNC_STATE_KEY);
    return raw ? (JSON.parse(raw) as SyncState) : {};
  } catch {
    return {};
  }
}

export function saveSyncState(state: SyncState): void {
  try {
    localStorage.setItem(SYNC_STATE_KEY, JSON.stringify(state));
  } catch {
    /* storage full or blocked: the next sync simply starts from what the server says */
  }
}

/** Everything the browser keeps about conversations (used on sign-out and when another user signs in on this browser). */
export function clearLocalConversations(keys: string[]): void {
  try {
    [SYNC_STATE_KEY, SYNC_OWNER_KEY, ...keys].forEach((key) => localStorage.removeItem(key));
  } catch {
    /* nothing to clear */
  }
}

/** The local copy of a conversation that lost a conflict: a new conversation, so the next sync uploads it as one. */
export function conflictCopy(session: SyncedSession, messages: ChatMessage[], now = Date.now()): { session: SyncedSession; messages: ChatMessage[] } {
  const id = `${session.id}-local-${now}`;
  return {
    session: { id, title: t(getLang(), 'sync.localCopy', { title: session.title }), isPinned: false, updatedAt: new Date(now).toISOString() },
    messages,
  };
}

export class ConflictError extends Error {
  constructor(public readonly server: RemoteConversation) {
    super('conflict');
  }
}

async function json<T>(response: Response): Promise<T> {
  if (isUnauthorized(response)) throw new Error('unauthorized');
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as T;
}

export async function listRemote(): Promise<RemoteSummary[]> {
  return json<RemoteSummary[]>(await apiFetch('/api/conversations', { cache: 'no-store' }));
}

export async function getRemote(id: string): Promise<RemoteConversation> {
  return json<RemoteConversation>(await apiFetch(`/api/conversations/${encodeURIComponent(id)}`, { cache: 'no-store' }));
}

/** Save one conversation. Resolves with the new version; throws `ConflictError` (with the server's copy) on 409. */
export async function putRemote(session: SyncedSession, messages: ChatMessage[], baseVersion: string | null): Promise<RemoteSummary> {
  const send = (msgs: ChatMessage[]) =>
    apiFetch(`/api/conversations/${encodeURIComponent(session.id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: session.title, pinned: session.isPinned, messages: msgs, base_updated_at: baseVersion }),
    });
  let response = await send(sanitizeMessagesForStorage({ [session.id]: messages })[session.id]);
  if (response.status === 413) {
    // too big (large dashboard tables): keep the dashboards but not their data grids, they are rebuilt by re-running the analysis
    const light = messages.map((m) => (m.dashboardSpec?.table ? { ...m, dashboardSpec: { ...m.dashboardSpec, table: { ...m.dashboardSpec.table, rows: [], truncated: true } } } : m));
    response = await send(light);
  }
  if (response.status === 409) throw new ConflictError((await response.json()) as RemoteConversation);
  return json<RemoteSummary>(response);
}

export async function deleteRemote(id: string): Promise<void> {
  const response = await apiFetch(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (isUnauthorized(response)) throw new Error('unauthorized');
}
