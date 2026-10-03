import { beforeEach, describe, expect, it, vi } from 'vitest';
import { clearLocalConversations, migrateLegacyLocalConversations } from '../../lib/conversationSync';
import { GUEST_OWNER, localKey, STORAGE_SESSIONS_KEY } from '../../lib/storage';

function stubLocalStorage(): Map<string, string> {
  const data = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  });
  return data;
}

describe('conversations are kept per account', () => {
  let data: Map<string, string>;
  beforeEach(() => {
    data = stubLocalStorage();
  });

  it('gives every account (and the guest) its own key', () => {
    const keys = ['alice', 'bob', GUEST_OWNER].map((o) => localKey(STORAGE_SESSIONS_KEY, o));
    expect(new Set(keys).size).toBe(3);
  });

  it('hands the old shared copy to its recorded owner only, and drops it for everyone else', () => {
    data.set(STORAGE_SESSIONS_KEY, '["alice chat"]');
    data.set('fpt_chat_owner', 'alice');

    migrateLegacyLocalConversations('bob');
    expect(data.get(localKey(STORAGE_SESSIONS_KEY, 'bob'))).toBeUndefined();
    expect(data.has(STORAGE_SESSIONS_KEY)).toBe(false); // gone: alice's chats are not left lying around for the next one either

    data.set(STORAGE_SESSIONS_KEY, '["alice chat"]');
    data.set('fpt_chat_owner', 'alice');
    migrateLegacyLocalConversations('alice');
    expect(data.get(localKey(STORAGE_SESSIONS_KEY, 'alice'))).toBe('["alice chat"]');
  });

  it('never hands an unowned old copy to anybody', () => {
    data.set(STORAGE_SESSIONS_KEY, '["who knows"]');
    migrateLegacyLocalConversations('alice');
    expect(data.get(localKey(STORAGE_SESSIONS_KEY, 'alice'))).toBeUndefined();
  });

  it('signing out clears that account only', () => {
    data.set(localKey(STORAGE_SESSIONS_KEY, 'alice'), 'a');
    data.set(localKey(STORAGE_SESSIONS_KEY, 'bob'), 'b');
    clearLocalConversations('alice');
    expect(data.has(localKey(STORAGE_SESSIONS_KEY, 'alice'))).toBe(false);
    expect(data.get(localKey(STORAGE_SESSIONS_KEY, 'bob'))).toBe('b');
  });
});
