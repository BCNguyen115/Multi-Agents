'use client';

import React, { useState, useEffect } from 'react';
import { Sidebar, ChatSession } from '../components/Sidebar';
import { Header } from '../components/Header';
import { ChatInterface } from '../components/ChatInterface';
import { SearchView } from '../components/SearchView';
import { CommandPalette } from '../components/CommandPalette';
import { ToastContainer } from '../components/ui/Toast';
import { useAuth } from '../context/AuthContext';
import { useConversationSync } from '../lib/useConversationSync';
import { ChatMessage } from '../lib/types';
import { safeSaveChatMessagesMap, STORAGE_SESSIONS_KEY, STORAGE_MESSAGES_KEY } from '../lib/storage';
import { exportDashboardToPDF, exportDashboardToPPTX } from '../lib/exportEngine';
import { toast } from '../lib/toast';
import { getLang, isDefaultChatTitle, t, useLang } from '../lib/i18n';
import { apiFetch } from '../lib/apiFetch';

export default function HomePage() {
  const [currentAgentMode, setCurrentAgentMode] = useState<string>('RAG Agent');
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  const [messagesMap, setMessagesMap] = useState<Record<string, ChatMessage[]>>({});
  const [viewMode, setViewMode] = useState<'chat' | 'search'>('chat');
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);
  const [isMounted, setIsMounted] = useState(false);
  const { me, setTheme } = useAuth(); // who is signed in, and the theme (AuthProvider, app/layout.tsx)
  const [lang] = useLang();

  // Initialize sessions & messages from localStorage
  useEffect(() => {
    setIsMounted(true);
    try {
      const storedSessions = localStorage.getItem(STORAGE_SESSIONS_KEY);
      const storedMap = localStorage.getItem(STORAGE_MESSAGES_KEY);

      let parsedSessions: ChatSession[] = storedSessions ? JSON.parse(storedSessions) : [];
      let parsedMap: Record<string, ChatMessage[]> = storedMap ? JSON.parse(storedMap) : {};

      if (parsedSessions.length === 0) {
        const defaultId = `session-${Date.now()}`;
        const defaultSession: ChatSession = {
          id: defaultId,
          title: t(getLang(), 'chat.newTitle'),
          isPinned: false,
          updatedAt: new Date().toISOString(),
        };
        parsedSessions = [defaultSession];
        parsedMap = { [defaultId]: [] };
      }

      setSessions(parsedSessions);
      setMessagesMap(parsedMap);
      setActiveSessionId(parsedSessions[0].id);
    } catch (e) {
      console.error('Failed to load chat history from localStorage', e);
      const defaultId = `session-${Date.now()}`;
      setSessions([{ id: defaultId, title: t(getLang(), 'chat.newTitle'), isPinned: false, updatedAt: new Date().toISOString() }]);
      setActiveSessionId(defaultId);
      setMessagesMap({ [defaultId]: [] });
    }
  }, []);

  // Chats follow a signed-in user across browsers: the server keeps them, this page syncs with it (see lib/conversationSync.ts)
  const startFreshChat = () => {
    const freshId = `session-${Date.now()}`;
    setSessions([{ id: freshId, title: t(getLang(), 'chat.newTitle'), isPinned: false, updatedAt: new Date().toISOString() }]);
    setMessagesMap({ [freshId]: [] });
    setActiveSessionId(freshId);
  };

  useConversationSync({
    enabled: Boolean(me?.authenticated),
    userId: me?.user ?? null,
    ready: isMounted && sessions.length > 0,
    sessions,
    messagesMap,
    setSessions,
    setMessagesMap,
    onOwnerChanged: startFreshChat,
  });

  // A conversation deleted on another device may be the open one: move to another (or a new) conversation.
  useEffect(() => {
    if (sessions.length > 0 && activeSessionId && !sessions.some((s) => s.id === activeSessionId)) {
      setActiveSessionId(sessions[0].id);
    }
  }, [sessions, activeSessionId]);

  // Save sessions & messagesMap to localStorage whenever they update
  useEffect(() => {
    if (sessions.length > 0) {
      try {
        localStorage.setItem(STORAGE_SESSIONS_KEY, JSON.stringify(sessions));
      } catch (e) {
        console.warn('Failed to save sessions to localStorage', e);
      }
    }
  }, [sessions]);

  useEffect(() => {
    if (Object.keys(messagesMap).length > 0) {
      safeSaveChatMessagesMap(messagesMap);
    }
  }, [messagesMap]);

  // Global Keyboard Shortcuts (Cmd+K, Cmd+Shift+D)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Cmd+K / Ctrl+K: Open Command Palette
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
      }
      // Cmd+Shift+D / Ctrl+Shift+D: Toggle Theme
      else if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'd') {
        e.preventDefault();
        handleToggleTheme();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
    // handleToggleTheme reads the current theme from <html> and setTheme is stable: subscribing once is enough
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeMessages = messagesMap[activeSessionId] || [];

  // Extract latest dashboard spec for export actions
  const latestDashboardMessage = [...activeMessages].reverse().find((m) => m.dashboardSpec);
  const activeDashboardSpec = latestDashboardMessage?.dashboardSpec || null;

  const handleToggleTheme = () => {
    const isDark = document.documentElement.classList.contains('dark') || document.documentElement.getAttribute('data-theme') === 'dark';
    setTheme(isDark ? 'light' : 'dark');
    toast.info(t(getLang(), isDark ? 'nav.themeLightOn' : 'nav.themeDarkOn'));
  };

  const handleSelectSession = (id: string) => {
    setActiveSessionId(id);
    setViewMode('chat');
  };

  const handleNewChat = () => {
    const newId = `session-${Date.now()}`;
    const newSession: ChatSession = {
      id: newId,
      title: t(getLang(), 'chat.newTitle'),
      isPinned: false,
      updatedAt: new Date().toISOString(),
    };

    setSessions((prev) => [newSession, ...prev]);
    setMessagesMap((prev) => ({ ...prev, [newId]: [] }));
    setActiveSessionId(newId);
    setViewMode('chat');
    toast.success(t(getLang(), 'chat.created'));
  };

  const handleDeleteSession = (id: string) => {
    setSessions((prev) => {
      const nextSessions = prev.filter((s) => s.id !== id);
      if (nextSessions.length === 0) {
        const fallbackId = `session-${Date.now()}`;
        const fallbackSession: ChatSession = {
          id: fallbackId,
          title: t(getLang(), 'chat.newTitle'),
          isPinned: false,
          updatedAt: new Date().toISOString(),
        };
        setActiveSessionId(fallbackId);
        setMessagesMap((m) => {
          const newMap = { ...m };
          delete newMap[id];
          newMap[fallbackId] = [];
          return newMap;
        });
        return [fallbackSession];
      }
      if (activeSessionId === id) {
        setActiveSessionId(nextSessions[0].id);
      }
      return nextSessions;
    });

    setMessagesMap((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    toast.info(t(getLang(), 'chat.deleted'));
  };

  const handleTogglePin = (id: string) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, isPinned: !s.isPinned } : s))
    );
  };

  const handleRenameSession = (id: string, newTitle: string) => {
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, title: newTitle } : s))
    );
  };

  const fetchSmartTitle = async (queryText: string, targetSessionId: string) => {
    try {
      const res = await apiFetch('/api/chat/title', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: queryText, session_id: targetSessionId }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data && data.title && typeof data.title === 'string' && data.title.trim()) {
          const smartTitle = data.title.trim().replace(/^["']|["']$/g, '');
          setSessions((prev) =>
            prev.map((s) =>
              s.id === targetSessionId
                ? { ...s, title: smartTitle, updatedAt: new Date().toISOString() }
                : s
            )
          );
        }
      }
    } catch (err) {
      console.warn('Smart title request error, keeping full query:', err);
    }
  };

  const handleSendMessage = (msg: ChatMessage) => {
    setMessagesMap((prev) => {
      const current = prev[activeSessionId] || [];
      return {
        ...prev,
        [activeSessionId]: [...current, msg],
      };
    });

    // Auto update session title if it's the default title and user just sent a message
    if (msg.role === 'user') {
      const targetSessionId = activeSessionId;
      const fullQuery = msg.content.trim();

      setSessions((prev) => {
        const currentSession = prev.find((s) => s.id === targetSessionId);
        const isDefaultTitle =
          !currentSession ||
          isDefaultChatTitle(currentSession.title);

        if (isDefaultTitle && fullQuery) {
          fetchSmartTitle(fullQuery, targetSessionId);

          return prev.map((s) =>
            s.id === targetSessionId
              ? { ...s, title: fullQuery, updatedAt: new Date().toISOString() }
              : s
          );
        }
        return prev;
      });
    }
  };

  const handleUpdateLastMessage = (updater: (prev: ChatMessage) => ChatMessage) => {
    setMessagesMap((prev) => {
      const current = prev[activeSessionId] || [];
      if (current.length === 0) return prev;
      const lastIdx = current.length - 1;
      const updatedLast = updater(current[lastIdx]);
      const nextList = [...current];
      nextList[lastIdx] = updatedLast;
      return {
        ...prev,
        [activeSessionId]: nextList,
      };
    });
  };

  const handleAgentSelect = (agentId: string) => {
    if (agentId === 'rag_agent' || agentId.includes('RAG')) {
      setCurrentAgentMode('RAG Agent');
    } else if (agentId === 'data_agent' || agentId.includes('Data')) {
      setCurrentAgentMode('Data Agent');
    } else if (agentId === 'search_agent' || agentId.includes('Search')) {
      setCurrentAgentMode('Search Agent');
    } else {
      setCurrentAgentMode(agentId.replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{1F1E0}-\u{1F1FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F900}-\u{1F9FF}\u{2B50}\u{2B55}\u{231A}\u{231B}\u{23E9}-\u{23EC}\u{23F0}\u{23F3}]/gu, '').trim());
    }
    toast.info(t(getLang(), 'nav.agentSwitched', { agent: agentId }));
  };

  if (!isMounted) {
    return (
      <div className="flex h-screen w-screen bg-background items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-accent-primary border-t-transparent rounded-full animate-spin" />
          <span className="text-foreground-muted text-sm font-medium font-mono">{t(lang, 'nav.loading')}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      {/* Toast Notification Container (Bottom-Right, Enterprise Sonner style) */}
      <ToastContainer />

      {/* Global Command Palette (Cmd+K / Ctrl+K) */}
      <CommandPalette
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
        sessions={sessions}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onSelectAgent={handleAgentSelect}
        onToggleTheme={handleToggleTheme}
        onTriggerUpload={() => {
          toast.info(t(getLang(), 'nav.uploadHint'), {
            title: t(getLang(), 'nav.uploadTitle'),
          });
        }}
        onExportPDF={() => {
          toast.info(t(getLang(), 'nav.pdfPreparing'), { title: t(getLang(), 'nav.pdfTitle') });
          exportDashboardToPDF();
        }}
        onExportPPTX={async () => {
          if (activeDashboardSpec) {
            try {
              toast.info(t(getLang(), 'nav.pptxPreparing'), { title: t(getLang(), 'nav.pptxTitle') });
              await exportDashboardToPPTX(activeDashboardSpec);
              toast.success(t(getLang(), 'nav.pptxDone'), { title: t(getLang(), 'nav.pptxTitle') });
            } catch (err: any) {
              toast.error(t(getLang(), 'nav.pptxFailed', { error: err?.message || t(getLang(), 'nav.unknownError') }), { title: t(getLang(), 'nav.exportFailedTitle') });
            }
          } else {
            toast.warning(t(getLang(), 'nav.noDashboard'), { title: t(getLang(), 'nav.noDashboardTitle') });
          }
        }}
      />

      {/* Left Navigation Sidebar */}
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        onTogglePin={handleTogglePin}
        onRenameSession={handleRenameSession}
        onOpenSearch={() => setIsCommandPaletteOpen(true)}
      />

      {/* Main Content Area */}
      <main id="main-content" tabIndex={-1} className="flex-1 flex flex-col h-full min-h-0 min-w-0 w-full max-w-full overflow-x-hidden relative bg-background overflow-y-hidden focus:outline-none">
        <Header
          currentAgent={currentAgentMode}
          onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
        />

        <ChatInterface
          currentAgentMode={currentAgentMode}
          onSelectAgentMode={handleAgentSelect}
          sessionId={activeSessionId}
          messages={activeMessages}
          onSendMessage={handleSendMessage}
          onUpdateLastMessage={handleUpdateLastMessage}
        />

        {viewMode === 'search' && (
          <SearchView
            sessions={sessions}
            onSelectSession={handleSelectSession}
            onClose={() => setViewMode('chat')}
          />
        )}
      </main>
    </div>
  );
}
