'use client';

import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  Search,
  PlusCircle,
  UploadCloud,
  SunMoon,
  FileDown,
  Presentation,
  Cpu,
  Database,
  Cloud,
  Globe,
  MessageSquare,
  ArrowRight,
  CornerDownLeft,
  X,
} from 'lucide-react';
import { ChatSession } from './Sidebar';
import { isDefaultChatTitle, t, useLang } from '../lib/i18n';

export interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  sessions: ChatSession[];
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onSelectAgent: (agentId: string) => void;
  onToggleTheme: () => void;
  onTriggerUpload: () => void;
  onExportPDF?: () => void;
  onExportPPTX?: () => void;
}

interface CommandItem {
  id: string;
  category: 'Actions' | 'Agents' | 'History';
  title: string;
  subtitle?: string;
  icon: React.ReactNode;
  shortcut?: string;
  action: () => void;
}

export function CommandPalette({
  isOpen,
  onClose,
  sessions,
  onSelectSession,
  onNewChat,
  onSelectAgent,
  onToggleTheme,
  onTriggerUpload,
  onExportPDF,
  onExportPPTX,
}: CommandPaletteProps) {
  const [lang] = useLang();
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Auto focus input on open
  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => {
        inputRef.current?.focus();
      }, 50);
    }
  }, [isOpen]);

  // Build commands
  const allCommands = useMemo<CommandItem[]>(() => {
    const list: CommandItem[] = [
      // Quick Actions
      {
        id: 'new-chat',
        category: 'Actions',
        title: t(lang, 'cmd.newChat'),
        subtitle: t(lang, 'cmd.newChatHint'),
        icon: <PlusCircle className="w-4 h-4 text-accent-primary" />,
        shortcut: '⌘N',
        action: () => {
          onNewChat();
          onClose();
        },
      },
      {
        id: 'upload-csv',
        category: 'Actions',
        title: t(lang, 'cmd.upload'),
        subtitle: t(lang, 'cmd.uploadHint'),
        icon: <UploadCloud className="w-4 h-4 text-accent-planner" />,
        shortcut: '⌘U',
        action: () => {
          onTriggerUpload();
          onClose();
        },
      },
      {
        id: 'toggle-theme',
        category: 'Actions',
        title: t(lang, 'cmd.theme'),
        subtitle: t(lang, 'cmd.themeHint'),
        icon: <SunMoon className="w-4 h-4 text-foreground-secondary" />,
        shortcut: '⌘⇧D',
        action: () => {
          onToggleTheme();
          onClose();
        },
      },
      {
        id: 'export-pdf',
        category: 'Actions',
        title: t(lang, 'cmd.pdf'),
        subtitle: t(lang, 'cmd.pdfHint'),
        icon: <FileDown className="w-4 h-4 text-foreground-secondary" />,
        shortcut: '⌘P',
        action: () => {
          onExportPDF?.();
          onClose();
        },
      },
      {
        id: 'export-pptx',
        category: 'Actions',
        title: t(lang, 'cmd.pptx'),
        subtitle: t(lang, 'cmd.pptxHint'),
        icon: <Presentation className="w-4 h-4 text-foreground-secondary" />,
        action: () => {
          onExportPPTX?.();
          onClose();
        },
      },

      // Agent Switchers
      {
        id: 'agent-data',
        category: 'Agents',
        title: t(lang, 'cmd.agentData'),
        subtitle: t(lang, 'cmd.agentDataHint'),
        icon: <Database className="w-4 h-4 text-accent-primary" />,
        action: () => {
          onSelectAgent('Data Agent');
          onClose();
        },
      },
      {
        id: 'agent-rag',
        category: 'Agents',
        title: t(lang, 'cmd.agentRag'),
        subtitle: t(lang, 'cmd.agentRagHint'),
        icon: <Cloud className="w-4 h-4 text-accent-planner" />,
        action: () => {
          onSelectAgent('RAG Agent');
          onClose();
        },
      },
      {
        id: 'agent-search',
        category: 'Agents',
        title: t(lang, 'cmd.agentSearch'),
        subtitle: t(lang, 'cmd.agentSearchHint'),
        icon: <Globe className="w-4 h-4 text-accent-executor" />,
        action: () => {
          onSelectAgent('Search Agent');
          onClose();
        },
      },
      {
        id: 'agent-db',
        category: 'Agents',
        title: t(lang, 'cmd.agentDb'),
        subtitle: t(lang, 'cmd.agentDbHint'),
        icon: <Cpu className="w-4 h-4 text-foreground-secondary" />,
        action: () => {
          onSelectAgent('Database Agent');
          onClose();
        },
      },
    ];

    // Session History items
    sessions.forEach((s) => {
      list.push({
        id: `session-${s.id}`,
        category: 'History',
        title: isDefaultChatTitle(s.title) ? t(lang, 'chat.newTitle') : s.title,
        subtitle: t(lang, 'cmd.updatedAt', { time: new Date(s.updatedAt).toLocaleTimeString(lang === 'vi' ? 'vi-VN' : 'en-GB', { hour: '2-digit', minute: '2-digit' }) }),
        icon: <MessageSquare className="w-4 h-4 text-foreground-muted" />,
        action: () => {
          onSelectSession(s.id);
          onClose();
        },
      });
    });

    return list;
  }, [
    lang,
    sessions,
    onNewChat,
    onClose,
    onTriggerUpload,
    onToggleTheme,
    onExportPDF,
    onExportPPTX,
    onSelectAgent,
    onSelectSession,
  ]);

  // Filter commands by query
  const filteredCommands = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return allCommands;
    return allCommands.filter(
      (c) =>
        c.title.toLowerCase().includes(q) ||
        (c.subtitle && c.subtitle.toLowerCase().includes(q)) ||
        c.category.toLowerCase().includes(q)
    );
  }, [allCommands, query]);

  // Keep selected index within bounds
  useEffect(() => {
    if (selectedIndex >= filteredCommands.length) {
      setSelectedIndex(Math.max(0, filteredCommands.length - 1));
    }
  }, [filteredCommands.length, selectedIndex]);

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current) {
      const activeEl = listRef.current.querySelector('[data-selected="true"]');
      if (activeEl) {
        activeEl.scrollIntoView({ block: 'nearest' });
      }
    }
  }, [selectedIndex]);

  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % Math.max(1, filteredCommands.length));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + filteredCommands.length) % Math.max(1, filteredCommands.length));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filteredCommands[selectedIndex]) {
        filteredCommands[selectedIndex].action();
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  if (!isOpen) return null;

  // Group filtered commands by category
  const categories: ('Actions' | 'Agents' | 'History')[] = ['Actions', 'Agents', 'History'];

  let globalIndex = -1;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t(lang, 'cmd.dialog')}
      className="fixed inset-0 z-[9990] flex items-start justify-center pt-20 px-4 select-none animate-fade-in"
    >
      {/* Backdrop: Dark scrim with blur completely separates the foreground from the page behind */}
      <div
        className="fixed inset-0 bg-black/50 dark:bg-black/70 backdrop-blur-md transition-opacity"
        onClick={onClose}
      />

      {/* Modal Dialog: Solid surface with border and token purity (Zero bleed-through) */}
      <div
        className="relative w-full max-w-xl bg-surface border border-border shadow-lg rounded-2xl overflow-hidden transition-colors z-10 flex flex-col max-h-[75vh] animate-fade-in-scale"
        onKeyDown={handleKeyDown}
      >
        {/* Search Input Bar */}
        <div className="flex items-center px-4 py-3 border-b border-border gap-3">
          <Search className="w-5 h-5 text-foreground-muted shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            placeholder={t(lang, 'cmd.placeholder')}
            className="w-full bg-transparent text-foreground placeholder:text-foreground-muted text-sm font-sans focus:outline-none"
          />
          {query ? (
            <button
              type="button"
              onClick={() => {
                setQuery('');
                inputRef.current?.focus();
              }}
              className="p-1 rounded-md text-foreground-muted hover:text-foreground hover:bg-surface-raised cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          ) : (
            <kbd className="px-1.5 py-0.5 text-2xs font-mono text-foreground-secondary bg-surface-raised border border-border rounded-md">
              ESC
            </kbd>
          )}
        </div>

        {/* Results List */}
        <div ref={listRef} className="flex-1 overflow-y-auto p-2 space-y-4">
          {filteredCommands.length === 0 ? (
            <div className="py-12 text-center text-sm text-foreground-muted">
              {t(lang, 'cmd.none')}
            </div>
          ) : (
            categories.map((category) => {
              const items = filteredCommands.filter((c) => c.category === category);
              if (items.length === 0) return null;

              return (
                <div key={category} className="space-y-1">
                  <div className="px-3 py-1.5 text-xs font-bold tracking-wider uppercase text-foreground-muted font-mono">
                    {category === 'Actions'
                      ? t(lang, 'cmd.catActions')
                      : category === 'Agents'
                      ? t(lang, 'cmd.catAgents')
                      : t(lang, 'cmd.catHistory')}
                  </div>

                  {items.map((cmd) => {
                    globalIndex++;
                    const isSelected = globalIndex === selectedIndex;
                    const thisIdx = globalIndex;

                    return (
                      <div
                        key={cmd.id}
                        data-selected={isSelected}
                        onClick={cmd.action}
                        onMouseEnter={() => setSelectedIndex(thisIdx)}
                        className={`group flex items-center justify-between px-3 py-2.5 rounded-xl text-xs transition-colors cursor-pointer ${
                          isSelected
                            ? 'bg-accent-primary text-white shadow-xs'
                            : 'text-foreground hover:bg-surface-raised'
                        }`}
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <div
                            className={`p-1.5 rounded-lg shrink-0 ${
                              isSelected
                                ? 'bg-white/20 text-white'
                                : 'bg-surface-raised text-foreground-secondary'
                            }`}
                          >
                            {cmd.icon}
                          </div>
                          <div className="min-w-0">
                            <p
                              className={`font-medium text-sm truncate ${
                                isSelected
                                  ? 'text-white'
                                  : 'text-foreground group-hover:text-accent-primary'
                              }`}
                            >
                              {cmd.title}
                            </p>
                            {cmd.subtitle && (
                              <p
                                className={`text-xs truncate ${
                                  isSelected
                                    ? 'text-white/80'
                                    : 'text-foreground-muted'
                                }`}
                              >
                                {cmd.subtitle}
                              </p>
                            )}
                          </div>
                        </div>

                        <div className="flex items-center gap-2 shrink-0">
                          {cmd.shortcut && (
                            <kbd
                              className={`px-1.5 py-0.5 text-2xs font-mono rounded-md ${
                                isSelected
                                  ? 'bg-white/20 text-white border border-white/30'
                                  : 'bg-surface-raised border border-border text-foreground-secondary'
                              }`}
                            >
                              {cmd.shortcut}
                            </kbd>
                          )}
                          {isSelected && <ArrowRight className="w-3.5 h-3.5 text-white/80" />}
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
            })
          )}
        </div>

        {/* Footer Hotkey Legend */}
        <div className="px-4 py-2.5 bg-surface-raised/80 border-t border-border flex items-center justify-between text-2xs font-mono text-foreground-muted">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <kbd className="px-1 py-0.5 rounded bg-surface border border-border text-foreground-secondary">↑</kbd>
              <kbd className="px-1 py-0.5 rounded bg-surface border border-border text-foreground-secondary">↓</kbd>
              <span>{t(lang, 'cmd.move')}</span>
            </span>
            <span className="flex items-center gap-1">
              <kbd className="px-1.5 py-0.5 rounded bg-surface border border-border text-foreground-secondary flex items-center gap-0.5">
                <CornerDownLeft className="w-2.5 h-2.5" />
                <span>Enter</span>
              </kbd>
              <span>{t(lang, 'cmd.run')}</span>
            </span>
          </div>
          <span className="text-foreground-muted">Linear / Raycast Grade</span>
        </div>
      </div>
    </div>
  );
}
