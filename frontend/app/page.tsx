'use client';

import React, { useState, useEffect } from 'react';
import { Sidebar, ChatSession } from '../components/Sidebar';
import { Header } from '../components/Header';
import { ChatInterface } from '../components/ChatInterface';
import { SearchView } from '../components/SearchView';
import { ChatMessage } from '../lib/types';
import { safeSaveChatMessagesMap, STORAGE_SESSIONS_KEY, STORAGE_MESSAGES_KEY } from '../lib/storage';

export default function HomePage() {
  const [currentAgentMode, setCurrentAgentMode] = useState<string>('RAG Agent');
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  const [messagesMap, setMessagesMap] = useState<Record<string, ChatMessage[]>>({});
  const [viewMode, setViewMode] = useState<'chat' | 'search'>('chat');
  const [isMounted, setIsMounted] = useState(false);

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
          title: 'Cuộc trò chuyện mới',
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
      setSessions([{ id: defaultId, title: 'Cuộc trò chuyện mới', isPinned: false, updatedAt: new Date().toISOString() }]);
      setActiveSessionId(defaultId);
      setMessagesMap({ [defaultId]: [] });
    }
  }, []);

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

  const activeMessages = messagesMap[activeSessionId] || [];

  const handleSelectSession = (id: string) => {
    setActiveSessionId(id);
    setViewMode('chat');
  };

  const handleNewChat = () => {
    const newId = `session-${Date.now()}`;
    const newSession: ChatSession = {
      id: newId,
      title: 'Cuộc trò chuyện mới',
      isPinned: false,
      updatedAt: new Date().toISOString(),
    };

    setSessions((prev) => [newSession, ...prev]);
    setMessagesMap((prev) => ({ ...prev, [newId]: [] }));
    setActiveSessionId(newId);
    setViewMode('chat');
  };

  const handleDeleteSession = (id: string) => {
    setSessions((prev) => {
      const nextSessions = prev.filter((s) => s.id !== id);
      if (nextSessions.length === 0) {
        const fallbackId = `session-${Date.now()}`;
        const fallbackSession: ChatSession = {
          id: fallbackId,
          title: 'Cuộc trò chuyện mới',
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
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id === activeSessionId && (s.title === 'Cuộc trò chuyện mới' || s.title === 'New chat')) {
            const shortTitle = msg.content.length > 28 ? msg.content.substring(0, 28) + '...' : msg.content;
            return { ...s, title: shortTitle, updatedAt: new Date().toISOString() };
          }
          return s;
        })
      );
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
    if (agentId === 'rag_agent' || agentId === 'RAG Agent') {
      setCurrentAgentMode('RAG Agent');
    } else if (agentId === 'data_agent' || agentId === 'Data Agent') {
      setCurrentAgentMode('📊 Data Agent');
    } else if (agentId === 'search_agent' || agentId === 'Search Agent') {
      setCurrentAgentMode('🌐 Search Agent');
    } else {
      setCurrentAgentMode(agentId);
    }
  };

  if (!isMounted) {
    return (
      <div className="flex h-screen w-screen bg-[#F8F9FA] items-center justify-center">
        <div className="animate-pulse text-slate-400 text-sm font-medium">Đang tải giao diện...</div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#F8F9FA]">
      {/* Left Navigation Sidebar */}
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
        onTogglePin={handleTogglePin}
        onRenameSession={handleRenameSession}
        onOpenSearch={() => setViewMode('search')}
      />

      {/* Main Workspace Area (BẮT BUỘC có min-h-0 flex-col min-w-0 overflow-x-hidden) */}
      <main className="flex-1 flex flex-col h-full min-h-0 min-w-0 w-full max-w-full overflow-x-hidden relative bg-white overflow-y-hidden">
        <Header />
        
        {viewMode === 'search' ? (
          <SearchView
            sessions={sessions}
            onSelectSession={handleSelectSession}
            onClose={() => setViewMode('chat')}
          />
        ) : (
          <ChatInterface
            currentAgentMode={currentAgentMode}
            onSelectAgentMode={handleAgentSelect}
            sessionId={activeSessionId}
            messages={activeMessages}
            onSendMessage={handleSendMessage}
            onUpdateLastMessage={handleUpdateLastMessage}
          />
        )}
      </main>
    </div>
  );
}
