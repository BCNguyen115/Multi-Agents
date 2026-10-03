import { ChatMessage } from './types';

export const STORAGE_SESSIONS_KEY = 'fpt_chat_sessions';
export const STORAGE_MESSAGES_KEY = 'fpt_chat_messages_map';

/** Whose chats the browser holds when nobody is signed in. */
export const GUEST_OWNER = 'guest';

/** The browser's copy is kept per account (`<key>:<user>`): one account never reads or overwrites another's chats. */
export const localKey = (base: string, owner: string): string => `${base}:${owner}`;

/** Rows of a dashboard's data table kept in localStorage (the full table is re-created by re-running the analysis). */
export const MAX_STORED_TABLE_ROWS = 2000;

/**
 * Lọc bỏ dữ liệu nặng trước khi lưu vào localStorage: chỉ giữ tối đa MAX_STORED_TABLE_ROWS dòng của bảng
 * (một bản duy nhất, đánh dấu `truncated`), không nhân bản dữ liệu.
 */
export function sanitizeMessagesForStorage(messagesMap: Record<string, ChatMessage[]>): Record<string, ChatMessage[]> {
  const sanitizedMap: Record<string, ChatMessage[]> = {};

  for (const [sessionId, messages] of Object.entries(messagesMap)) {
    sanitizedMap[sessionId] = messages.map((msg) => {
      const rows = msg.dashboardSpec?.table?.rows;
      if (!msg.dashboardSpec || !Array.isArray(rows) || rows.length <= MAX_STORED_TABLE_ROWS) return msg;
      return {
        ...msg,
        dashboardSpec: {
          ...msg.dashboardSpec,
          table: { ...msg.dashboardSpec.table, rows: rows.slice(0, MAX_STORED_TABLE_ROWS), truncated: true },
        },
      };
    });
  }

  return sanitizedMap;
}

/**
 * Ghi dữ liệu tin nhắn an toàn vào localStorage chống lỗi QuotaExceededError & crash React app.
 */
export function safeSaveChatMessagesMap(messagesMap: Record<string, ChatMessage[]>, key: string = STORAGE_MESSAGES_KEY) {
  if (typeof window === 'undefined') return;

  try {
    const sanitizedData = sanitizeMessagesForStorage(messagesMap);
    localStorage.setItem(key, JSON.stringify(sanitizedData));
  } catch (error: any) {
    if (
      error &&
      (error.name === 'QuotaExceededError' ||
        error.name === 'NS_ERROR_DOM_QUOTA_REACHED' ||
        error.code === 22 ||
        error.code === 1014)
    ) {
      console.warn('localStorage quota exceeded! Attempting auto-cleanup of old sessions...');

      // Tự động xóa bớt 50% số session cũ nhất để giải phóng bộ nhớ
      const sessionIds = Object.keys(messagesMap);
      if (sessionIds.length > 1) {
        const halfIndex = Math.ceil(sessionIds.length / 2);
        const recentSessionsMap: Record<string, ChatMessage[]> = {};

        sessionIds.slice(halfIndex).forEach((id) => {
          recentSessionsMap[id] = messagesMap[id];
        });

        try {
          const sanitizedReduced = sanitizeMessagesForStorage(recentSessionsMap);
          localStorage.setItem(key, JSON.stringify(sanitizedReduced));
          return;
        } catch (e) {
          console.warn('Second attempt to save reduced chat history failed, clearing heavy specs...');
        }
      }

      // Xóa bỏ hoàn toàn mảng rows trong dashboardSpec nếu dung lượng vẫn bị max
      try {
        const ultraCleanMap: Record<string, ChatMessage[]> = {};
        for (const [sId, msgs] of Object.entries(messagesMap)) {
          ultraCleanMap[sId] = msgs.map((m) => {
            if (m.dashboardSpec && m.dashboardSpec.table) {
              const { rows, ...cleanTbl } = m.dashboardSpec.table;
              return {
                ...m,
                dashboardSpec: { ...m.dashboardSpec, table: { ...cleanTbl, rows: [] } },
              };
            }
            return m;
          });
        }
        localStorage.setItem(key, JSON.stringify(ultraCleanMap));
      } catch (finalErr) {
        console.error('Critical storage quota reached. Clearing localStorage messages map to prevent crash.');
        localStorage.removeItem(key);
      }
    }
  }
}
