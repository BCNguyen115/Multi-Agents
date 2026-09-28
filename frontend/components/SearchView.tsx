'use client';

import React, { useState, useMemo, useEffect, useRef } from 'react';
import { Search, X, MessageSquare, Clock, ChevronRight, Inbox, Command } from 'lucide-react';
import { ChatSession } from './Sidebar';

interface SearchViewProps {
  sessions: ChatSession[];
  onSelectSession: (id: string) => void;
  onClose: () => void;
}

export function SearchView({ sessions, onSelectSession, onClose }: SearchViewProps) {
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const filteredSessions = useMemo(() => {
    if (!query.trim()) return sessions;
    const lower = query.toLowerCase();
    return sessions.filter(
      (s) =>
        s.title.toLowerCase().includes(lower) ||
        s.id.toLowerCase().includes(lower)
    );
  }, [sessions, query]);

  const formatDate = (dateStr: string) => {
    try {
      const d = new Date(dateStr);
      const now = new Date();
      const diffMs = now.getTime() - d.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      const diffHrs = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);
      if (diffMins < 1) return 'Vừa xong';
      if (diffMins < 60) return `${diffMins} phút trước`;
      if (diffHrs < 24) return `${diffHrs} giờ trước`;
      if (diffDays === 1) return 'Hôm qua';
      if (diffDays < 7) return `${diffDays} ngày trước`;
      return d.toLocaleDateString('vi-VN');
    } catch {
      return dateStr;
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-16 sm:pt-24 px-4 bg-black/60 backdrop-blur-md animate-fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Command Palette Tìm kiếm hội thoại"
    >
      <div className="w-full max-w-2xl bg-surface border border-border-strong rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[75vh] animate-scale-up">
        {/* Search Input Bar */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-border bg-surface-raised/40 shrink-0">
          <Search className="w-5 h-5 text-accent-primary shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Tìm kiếm cuộc trò chuyện (nhấn ESC để thoát)..."
            className="flex-1 bg-transparent text-foreground placeholder-foreground-muted text-sm focus:outline-none"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              className="text-foreground-muted hover:text-foreground p-1 rounded-md transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-primary/40"
              title="Xóa tìm kiếm"
            >
              <X className="w-4 h-4" />
            </button>
          )}
          <kbd className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 text-xs font-mono text-foreground-muted bg-surface border border-border rounded-md shadow-2xs select-none">
            ESC
          </kbd>
        </div>

        {/* Results list */}
        <div className="flex-1 overflow-y-auto p-3 space-y-1.5">
          {filteredSessions.length > 0 ? (
            <>
              <div className="px-2 py-1 text-xs text-foreground-muted font-semibold flex items-center justify-between">
                <span>{query ? `${filteredSessions.length} kết quả phù hợp` : `${sessions.length} cuộc trò chuyện`}</span>
                <span className="flex items-center gap-1 text-xs font-mono">
                  <Command className="w-3 h-3" /> K
                </span>
              </div>
              {filteredSessions.map((session) => (
                <button
                  key={session.id}
                  type="button"
                  onClick={() => onSelectSession(session.id)}
                  className="w-full flex items-center gap-3 p-3 bg-surface hover:bg-surface-raised border border-transparent hover:border-border rounded-xl transition-all duration-150 cursor-pointer text-left group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
                >
                  <div className="w-9 h-9 rounded-lg bg-surface-raised flex items-center justify-center shrink-0 group-hover:bg-accent-primary/10 transition-colors">
                    <MessageSquare className="w-4 h-4 text-foreground-muted group-hover:text-accent-primary transition-colors" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p title={session.title} className="text-sm font-semibold text-foreground truncate group-hover:text-accent-primary transition-colors">
                      {session.title}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <Clock className="w-3 h-3 text-foreground-muted" />
                      <span className="text-xs text-foreground-muted font-mono tabular-nums">
                        {formatDate(session.updatedAt)}
                      </span>
                      {session.isPinned && (
                        <span className="text-xs bg-accent-planner/10 text-accent-planner border border-accent-planner/20 px-2 py-0.2 rounded-full font-semibold">
                          Đã ghim
                        </span>
                      )}
                    </div>
                  </div>
                  <ChevronRight className="w-4 h-4 text-foreground-muted group-hover:text-accent-primary transition-all group-hover:translate-x-0.5 shrink-0" />
                </button>
              ))}
            </>
          ) : (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="w-14 h-14 rounded-2xl bg-surface-raised flex items-center justify-center mb-3">
                <Inbox className="w-7 h-7 text-foreground-muted" />
              </div>
              <p className="text-sm font-semibold text-foreground-secondary mb-1">Không tìm thấy kết quả</p>
              <p className="text-xs text-foreground-muted">
                {query ? `Không có cuộc trò chuyện nào khớp với "${query}"` : 'Chưa có cuộc trò chuyện nào'}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
