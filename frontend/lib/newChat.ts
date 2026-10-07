import type { ChatMessage } from './types';

type MessagesMap = Record<string, ChatMessage[] | undefined>;

/** A conversation nobody has written in. One whose messages are not known (not in the map) is not: a real chat must
 * never be mistaken for an empty one. */
export const isUnwritten = (messages: ChatMessage[] | undefined): boolean =>
  Array.isArray(messages) && !messages.some((m) => m.role === 'user');

/**
 * The conversation "New chat" should go back to instead of creating another: the open one if nobody has written in it,
 * else the first other one nobody has written in.
 */
export function findEmptyChat(sessions: { id: string }[], messagesMap: MessagesMap, activeId: string): string | null {
  if (isUnwritten(messagesMap[activeId]) && sessions.some((s) => s.id === activeId)) return activeId;
  return sessions.find((s) => isUnwritten(messagesMap[s.id]))?.id ?? null;
}

/** The sidebar order: conversations nobody has written in first (the one made at sign-in must not sit under the chats
 * the server sends back), everything else in the order it already had. */
export function emptyFirst<T extends { id: string }>(sessions: T[], messagesMap: MessagesMap): T[] {
  const empty = sessions.filter((s) => isUnwritten(messagesMap[s.id]));
  return empty.length === 0 || empty.length === sessions.length ? sessions : [...empty, ...sessions.filter((s) => !empty.includes(s))];
}
