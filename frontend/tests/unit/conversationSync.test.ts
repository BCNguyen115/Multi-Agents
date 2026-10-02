import { describe, expect, it } from 'vitest';
import { conflictCopy, fingerprint, isBusy, planSync, type LocalView, type RemoteSummary, type SyncState } from '../../lib/conversationSync';
import type { ChatMessage } from '../../lib/types';

const local = (id: string, hash: string, busy = false): LocalView => ({ id, hash, busy });
const remote = (id: string, updated_at: string): RemoteSummary => ({ id, title: id, pinned: false, updated_at });
const known = (version: string, hash: string) => ({ version, hash });

const plan = (l: LocalView[], r: RemoteSummary[], s: SyncState) => planSync(l, r, s);
const empty = { pull: [], push: [], deleteRemote: [], deleteLocal: [], conflicts: [] };

describe('planSync', () => {
  it('does nothing when both sides still match what was last agreed', () => {
    expect(plan([local('a', 'h1')], [remote('a', 'v1')], { a: known('v1', 'h1') })).toEqual(empty);
  });

  it('pushes what only this browser changed, and pulls what only the server changed', () => {
    const state = { a: known('v1', 'h1'), b: known('v1', 'h1') };
    expect(plan([local('a', 'h2'), local('b', 'h1')], [remote('a', 'v1'), remote('b', 'v2')], state)).toEqual({ ...empty, push: ['a'], pull: ['b'] });
  });

  it('calls it a conflict when both changed, or when two histories never met', () => {
    expect(plan([local('a', 'h2')], [remote('a', 'v2')], { a: known('v1', 'h1') }).conflicts).toEqual(['a']);
    expect(plan([local('a', 'h1')], [remote('a', 'v1')], {}).conflicts).toEqual(['a']);
  });

  it('uploads new local conversations and downloads new remote ones', () => {
    expect(plan([local('mine', 'h')], [remote('theirs', 'v')], {})).toEqual({ ...empty, push: ['mine'], pull: ['theirs'] });
  });

  it('follows deletions: gone on the server -> delete here, gone here -> delete there', () => {
    expect(plan([local('a', 'h1')], [], { a: known('v1', 'h1') })).toEqual({ ...empty, deleteLocal: ['a'] });
    expect(plan([], [remote('a', 'v1')], { a: known('v1', 'h1') })).toEqual({ ...empty, deleteRemote: ['a'] });
  });

  it('never deletes unsaved work: edits made here to a conversation deleted elsewhere are uploaded again', () => {
    expect(plan([local('a', 'h2')], [], { a: known('v1', 'h1') })).toEqual({ ...empty, push: ['a'] });
  });

  it('does not save a conversation whose reply is still being written', () => {
    expect(plan([local('a', 'h2', true)], [remote('a', 'v1')], { a: known('v1', 'h1') })).toEqual(empty);
    expect(plan([local('new', 'h', true)], [], {})).toEqual(empty);
  });

  it('forgets a conversation that is gone on both sides', () => {
    expect(plan([], [], { a: known('v1', 'h1') })).toEqual(empty);
  });
});

describe('fingerprint', () => {
  const message = (content: string): ChatMessage => ({ id: 'm', role: 'user', content });

  it('is stable for equal content and changes with the title, pin state or messages', () => {
    const base = fingerprint({ title: 't', isPinned: false }, [message('a')]);
    expect(fingerprint({ title: 't', isPinned: false }, [message('a')])).toBe(base);
    expect(fingerprint({ title: 'u', isPinned: false }, [message('a')])).not.toBe(base);
    expect(fingerprint({ title: 't', isPinned: true }, [message('a')])).not.toBe(base);
    expect(fingerprint({ title: 't', isPinned: false }, [message('b')])).not.toBe(base);
  });

  it('knows a reply is still loading', () => {
    expect(isBusy([message('a'), { ...message('b'), role: 'assistant', status: 'loading' }])).toBe(true);
    expect(isBusy([{ ...message('b'), role: 'assistant', status: 'complete' }])).toBe(false);
  });
});

describe('conflictCopy', () => {
  it('keeps the local text as a new conversation, so the next sync uploads it as one', () => {
    const messages: ChatMessage[] = [{ id: 'm', role: 'user', content: 'giữ lại' }];
    const copy = conflictCopy({ id: 'session-1', title: 'NDA', isPinned: true, updatedAt: 'x' }, messages, 1_000);
    expect(copy.session.id).toBe('session-1-local-1000');
    expect(copy.session.title).toBe('NDA (bản trên máy này)');
    expect(copy.session.isPinned).toBe(false);
    expect(copy.messages).toBe(messages);
  });
});
