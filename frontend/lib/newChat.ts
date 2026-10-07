import type { ChatMessage } from './types';

/**
 * The conversation "New chat" should go back to instead of creating another: the open one if nobody has written in it,
 * else the first other one nobody has written in. A conversation whose messages are not known (not in the map) is never
 * reused, so a real chat is never mistaken for an empty one.
 */
export function findEmptyChat(
  sessions: { id: string }[],
  messagesMap: Record<string, ChatMessage[] | undefined>,
  activeId: string,
): string | null {
  const isEmpty = (id: string) => {
    const messages = messagesMap[id];
    return Array.isArray(messages) && !messages.some((m) => m.role === 'user');
  };
  if (isEmpty(activeId) && sessions.some((s) => s.id === activeId)) return activeId;
  return sessions.find((s) => isEmpty(s.id))?.id ?? null;
}
