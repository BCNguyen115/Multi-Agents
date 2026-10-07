'use client';

import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { PanelLeft, PenSquare, Search, Pin, MoreVertical, Trash2, Edit3, MessageSquare, Inbox, Info } from 'lucide-react';
import { FptLogo } from './ui/FptLogo';
import { useAuth } from '../context/AuthContext';
import { UserProfileWidget } from './user/UserProfileWidget';
import { isDefaultChatTitle, t, useLang, type Lang, type MessageKey } from '../lib/i18n';

/** A chat that still has the default title shows it in the interface language. */
const displayTitle = (lang: Lang, title: string): string => (isDefaultChatTitle(title) ? t(lang, 'chat.newTitle') : title);

export interface ChatSession {
  id: string;
  title: string;
  isPinned: boolean;
  updatedAt: string;
}

interface SidebarProps {
  sessions: ChatSession[];
  activeSessionId: string;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  /** A conversation to draw the eye to ("New chat" sent the user back to it); `n` changes on every request. */
  flash?: { id: string; n: number } | null;
  onDeleteSession: (id: string) => void;
  onTogglePin: (id: string) => void;
  onRenameSession?: (id: string, newTitle: string) => void;
  onOpenSearch?: () => void;
}

// Group sessions by time period
function groupSessionsByDate(sessions: ChatSession[]): { label: MessageKey; sessions: ChatSession[] }[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const sevenDaysAgo = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);
  const thirtyDaysAgo = new Date(today.getTime() - 30 * 24 * 60 * 60 * 1000);

  const groups: { label: MessageKey; sessions: ChatSession[] }[] = [
    { label: 'sidebar.group.today', sessions: [] },
    { label: 'sidebar.group.week', sessions: [] },
    { label: 'sidebar.group.month', sessions: [] },
    { label: 'sidebar.group.older', sessions: [] },
  ];

  sessions.forEach((s) => {
    const updated = new Date(s.updatedAt);
    if (updated >= today) {
      groups[0].sessions.push(s);
    } else if (updated >= sevenDaysAgo) {
      groups[1].sessions.push(s);
    } else if (updated >= thirtyDaysAgo) {
      groups[2].sessions.push(s);
    } else {
      groups[3].sessions.push(s);
    }
  });

  return groups.filter((g) => g.sessions.length > 0);
}

const SIDEBAR_STATE_KEY = 'sidebar_collapsed';
/** Below Tailwind's `md`: the sidebar is a rail, and opens over the page instead of pushing it. */
const MOBILE_QUERY = '(max-width: 767px)';

export function Sidebar({
  sessions = [],
  activeSessionId,
  onSelectSession,
  onNewChat,
  flash,
  onOpenSearch,
  onDeleteSession,
  onTogglePin,
  onRenameSession,
}: SidebarProps) {
  const [lang] = useLang();
  const { isGuest, config, openAuthModal } = useAuth();
  // Narrow screens start with the rail; wide ones restore the saved choice. (The page mounts this component on the client
  // only, after its own loading screen, so reading window here cannot cause a hydration mismatch.)
  const [isMobile, setIsMobile] = useState(() => typeof window !== 'undefined' && window.matchMedia(MOBILE_QUERY).matches);
  const [isOpen, setIsOpen] = useState(() => {
    if (typeof window === 'undefined' || window.matchMedia(MOBILE_QUERY).matches) return typeof window === 'undefined';
    try {
      return localStorage.getItem(SIDEBAR_STATE_KEY) !== 'true';
    } catch {
      return true;
    }
  });
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');

  // Crossing the breakpoint: the expanded sidebar of a wide screen would cover a phone, so fold it into the rail
  useEffect(() => {
    const query = window.matchMedia(MOBILE_QUERY);
    const onChange = () => {
      setIsMobile(query.matches);
      if (query.matches) setIsOpen(false);
    };
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  // After choosing something on a phone, the overlay has done its job
  const afterNav = () => {
    if (isMobile) setIsOpen(false);
  };

  // Publish current width as a CSS var so fixed/fullscreen overlays (e.g. DynamicDashboard)
  // can offset themselves instead of rendering underneath the sidebar. On a phone the open sidebar floats over the page,
  // so the space it takes from the page is the rail's.
  useEffect(() => {
    document.documentElement.style.setProperty('--sidebar-width', isOpen && !isMobile ? '16rem' : '4rem');
  }, [isOpen, isMobile]);

  // Global Cmd+B / Ctrl+B to toggle sidebar
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        setIsOpen((prev) => {
          const next = !prev;
          try {
            localStorage.setItem(SIDEBAR_STATE_KEY, next ? 'false' : 'true');
          } catch {}
          return next;
        });
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const toggleSidebar = (open: boolean) => {
    setIsOpen(open);
    if (isMobile) return; // the phone's open/closed state is not the desktop preference
    try {
      localStorage.setItem(SIDEBAR_STATE_KEY, open ? 'false' : 'true');
    } catch {}
  };

  const pinnedSessions = sessions.filter((s: ChatSession) => s.isPinned);
  const recentSessions = sessions.filter((s: ChatSession) => !s.isPinned);
  const groupedRecents = groupSessionsByDate(recentSessions);

  const handleStartRename = (session: ChatSession) => {
    setEditingSessionId(session.id);
    setEditingTitle(displayTitle(lang, session.title));
    setActiveMenuId(null);
  };

  const handleCancelRename = () => {
    setEditingSessionId(null);
  };

  const handleSaveRename = (id: string) => {
    if (editingTitle.trim() && onRenameSession) {
      onRenameSession(id, editingTitle.trim());
    }
    setEditingSessionId(null);
  };

  return (
    <>
    {/* Phone, sidebar open: it floats over the page, so a spacer keeps the rail's place and a scrim closes it */}
    {isOpen && <div className="md:hidden w-16 shrink-0" aria-hidden="true" />}
    {isOpen && <div className="md:hidden fixed inset-0 z-50 bg-black/50" onClick={() => setIsOpen(false)} aria-hidden="true" />}
    <aside
      className={`
        h-dvh bg-background-secondary
        border-r border-border
        transition-[width] duration-300 ease-in-out
        flex flex-col shrink-0 overflow-hidden select-none relative z-sidebar
        ${isOpen ? 'w-64 max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:shadow-lg' : 'w-16'}
      `}
    >
      {/* 1. SIDEBAR HEADER */}
      <div className="h-14 flex items-center px-2 border-b border-border shrink-0 relative overflow-hidden whitespace-nowrap">
        {/* Logo Slot */}
        <div className="w-12 h-12 flex items-center justify-center shrink-0 relative group cursor-pointer">
          <FptLogo
            className={`h-6 w-auto object-contain transition-opacity duration-200 ease-out ${!isOpen ? 'group-hover:opacity-0' : ''}`}
          />

          {!isOpen && (
            <button
              type="button"
              onClick={() => toggleSidebar(true)}
              className="absolute inset-0 m-auto w-8 h-8 flex items-center justify-center rounded-lg bg-surface-raised hover:bg-surface-overlay text-accent-primary opacity-0 group-hover:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100 transition-opacity duration-200 ease-out cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
              title={t(lang, 'sidebar.expand')}
              aria-label={t(lang, 'sidebar.expand')}
            >
              <PanelLeft className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Brand Text & Toggle (Expanded) */}
        <div className={`flex items-center justify-between flex-1 overflow-hidden whitespace-nowrap transition-[opacity,visibility] duration-300 ease-in-out ${isOpen ? 'opacity-100 ml-1' : 'opacity-0 pointer-events-none invisible'}`}>
          <span className="font-bold text-foreground whitespace-nowrap text-base">
            FPT<span className="text-accent-primary">AgentHub</span>
          </span>
          <button
            type="button"
            onClick={() => toggleSidebar(false)}
            className="p-1.5 rounded-lg hover:bg-surface-raised text-foreground-muted hover:text-foreground transition-colors duration-200 ease-out cursor-pointer shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
            title={t(lang, 'sidebar.collapse')}
            aria-label={t(lang, 'sidebar.collapse')}
          >
            <PanelLeft className="w-5 h-5" />
          </button>
        </div>
      </div>

      {/* 2. ACTION BUTTONS (New Chat & Search) */}
      <div className="py-2.5 space-y-1 border-b border-border px-2 shrink-0 overflow-hidden whitespace-nowrap">
        <button
          type="button"
          onClick={() => { onNewChat(); afterNav(); }}
          className="flex items-center h-10 px-0 rounded-xl hover:bg-surface-raised w-full transition-colors duration-200 ease-out group cursor-pointer overflow-hidden whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
          title={t(lang, 'sidebar.newChat')}
        >
          <div className="w-12 h-10 flex items-center justify-center shrink-0">
            <PenSquare className="w-5 h-5 text-foreground-secondary" />
          </div>
          <span className={`text-sm font-medium text-foreground-secondary whitespace-nowrap transition-[opacity,visibility] duration-300 ease-in-out ${isOpen ? 'opacity-100 ml-1' : 'opacity-0 pointer-events-none invisible'}`}>
            {t(lang, 'sidebar.newChat')}
          </span>
        </button>

        <button
          type="button"
          onClick={() => { onOpenSearch?.(); afterNav(); }}
          className="flex items-center h-10 px-0 rounded-xl hover:bg-surface-raised w-full transition-colors duration-200 ease-out group cursor-pointer overflow-hidden whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
          title={t(lang, 'sidebar.searchChats')}
        >
          <div className="w-12 h-10 flex items-center justify-center shrink-0">
            <Search className="w-5 h-5 text-foreground-secondary" />
          </div>
          <span className={`text-sm font-medium text-foreground-secondary whitespace-nowrap transition-[opacity,visibility] duration-300 ease-in-out ${isOpen ? 'opacity-100 ml-1' : 'opacity-0 pointer-events-none invisible'}`}>
            {t(lang, 'sidebar.searchChats')}
          </span>
        </button>
      </div>

      {/* Guest hint: the chats of a guest live in this browser only */}
      {isOpen && isGuest && config.login_enabled && (
        <p className="shrink-0 px-4 pt-3 flex items-center gap-2.5 text-xs text-foreground-secondary">
          <Info className="w-[18px] h-[18px] shrink-0" aria-hidden="true" />
          <span>
            <button
              type="button"
              onClick={() => openAuthModal('signin')}
              className="underline text-foreground cursor-pointer rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
            >
              {t(lang, 'user.signIn')}
            </button>{' '}
            {t(lang, 'user.saveActivity')}
          </span>
        </p>
      )}

      {/* 3. SESSION HISTORY (Pinned + Grouped Recents) */}
      <div className="flex-1 overflow-y-auto px-2 py-3 space-y-4 overflow-x-hidden whitespace-nowrap">
        {/* Pinned Section */}
        {pinnedSessions.length > 0 && (
          <div>
            <div className={`px-3 text-xs font-mono font-semibold text-foreground-muted uppercase tracking-wider mb-1 flex items-center justify-between select-none whitespace-nowrap transition-[opacity,visibility] duration-300 ease-in-out ${isOpen ? 'opacity-100' : 'opacity-0 invisible'}`}>
              <span>{t(lang, 'sidebar.pinned')}</span>
              <Pin className="w-3 h-3 text-foreground-muted" />
            </div>
            {pinnedSessions.map((session: ChatSession) => (
              <ChatItem
                key={session.id}
                session={session}
                isOpen={isOpen}
                isActive={session.id === activeSessionId}
                flashKey={flash?.id === session.id ? flash.n : 0}
                onSelect={() => { onSelectSession(session.id); afterNav(); }}
                onDelete={() => onDeleteSession(session.id)}
                onTogglePin={() => onTogglePin(session.id)}
                onRename={() => handleStartRename(session)}
                isEditing={editingSessionId === session.id}
                editingTitle={editingTitle}
                setEditingTitle={setEditingTitle}
                onSaveRename={() => handleSaveRename(session.id)}
                onCancelRename={handleCancelRename}
                isMenuOpen={activeMenuId === session.id}
                setMenuOpen={(open: boolean) => setActiveMenuId(open ? session.id : null)}
              />
            ))}
          </div>
        )}

        {/* Grouped Recents */}
        {groupedRecents.length > 0 ? (
          groupedRecents.map((group) => (
            <div key={group.label}>
              <div className={`px-3 text-xs font-mono font-semibold text-foreground-muted uppercase tracking-wider mb-1 select-none whitespace-nowrap transition-[opacity,visibility] duration-300 ease-in-out ${isOpen ? 'opacity-100' : 'opacity-0 invisible'}`}>
                {t(lang, group.label)}
              </div>
              {group.sessions.map((session: ChatSession) => (
                <ChatItem
                  key={session.id}
                  session={session}
                  isOpen={isOpen}
                  isActive={session.id === activeSessionId}
                flashKey={flash?.id === session.id ? flash.n : 0}
                  onSelect={() => { onSelectSession(session.id); afterNav(); }}
                  onDelete={() => onDeleteSession(session.id)}
                  onTogglePin={() => onTogglePin(session.id)}
                  onRename={() => handleStartRename(session)}
                  isEditing={editingSessionId === session.id}
                  editingTitle={editingTitle}
                  setEditingTitle={setEditingTitle}
                  onSaveRename={() => handleSaveRename(session.id)}
                  onCancelRename={handleCancelRename}
                  isMenuOpen={activeMenuId === session.id}
                  setMenuOpen={(open: boolean) => setActiveMenuId(open ? session.id : null)}
                />
              ))}
            </div>
          ))
        ) : (
          recentSessions.length === 0 && isOpen && (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <div className="w-12 h-12 rounded-2xl bg-surface-raised flex items-center justify-center mb-3">
                <Inbox className="w-6 h-6 text-foreground-muted" />
              </div>
              <p className="text-sm font-medium text-foreground-secondary mb-1">{t(lang, 'sidebar.empty')}</p>
              <p className="text-xs text-foreground-muted">{t(lang, 'sidebar.emptyHint')}</p>
            </div>
          )
        )}
      </div>

      {/* 4. USER PROFILE: avatar, status and the settings menu */}
      <div className="shrink-0 border-t border-border p-2">
        <UserProfileWidget isCollapsed={!isOpen} />
      </div>
    </aside>
    </>
  );
}

// Sub-component: Chat Item with Portal Dropdown
function ChatItem({
  session,
  isOpen,
  isActive,
  flashKey,
  onSelect,
  onDelete,
  onTogglePin,
  onRename,
  isEditing,
  editingTitle,
  setEditingTitle,
  onSaveRename,
  onCancelRename,
  isMenuOpen,
  setMenuOpen,
}: {
  session: ChatSession;
  isOpen: boolean;
  isActive: boolean;
  flashKey: number;
  onSelect: () => void;
  onDelete: () => void;
  onTogglePin: () => void;
  onRename: () => void;
  isEditing: boolean;
  editingTitle: string;
  setEditingTitle: (t: string) => void;
  onSaveRename: () => void;
  onCancelRename?: () => void;
  isMenuOpen: boolean;
  setMenuOpen: (open: boolean) => void;
}) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const itemRef = useRef<HTMLDivElement>(null);
  const [lang] = useLang();
  const shownTitle = displayTitle(lang, session.title);
  const [menuPos, setMenuPos] = useState<{ top: number; right: number } | null>(null);
  const [isHovered, setIsHovered] = useState(false);
  const [flashing, setFlashing] = useState(false);

  // "New chat" sent the user back to this conversation: bring the row into view and let it flash once
  useEffect(() => {
    if (!flashKey) return undefined;
    itemRef.current?.scrollIntoView({ block: 'nearest' });
    setFlashing(true);
    const timer = setTimeout(() => setFlashing(false), 900);
    return () => clearTimeout(timer);
  }, [flashKey]);
  const [tooltipPos, setTooltipPos] = useState<{ top: number; left: number } | null>(null);

  const handleMouseEnter = () => {
    if (!isOpen && itemRef.current) {
      const rect = itemRef.current.getBoundingClientRect();
      setTooltipPos({ top: rect.top, left: rect.right + 10 });
      setIsHovered(true);
    }
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
  };

  const handleToggleMenu = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!isMenuOpen && buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect();
      setMenuPos({
        top: rect.bottom + 4,
        right: window.innerWidth - rect.right,
      });
      setMenuOpen(true);
    } else {
      setMenuOpen(false);
    }
  };

  useEffect(() => {
    if (!isMenuOpen) return;

    const handleCloseMenu = (e: Event) => {
      if (buttonRef.current && buttonRef.current.contains(e.target as Node)) return;
      setMenuOpen(false);
    };

    const timer = setTimeout(() => {
      window.addEventListener('click', handleCloseMenu);
      window.addEventListener('scroll', handleCloseMenu, true);
    }, 50);

    return () => {
      clearTimeout(timer);
      window.removeEventListener('click', handleCloseMenu);
      window.removeEventListener('scroll', handleCloseMenu, true);
    };
  }, [isMenuOpen, setMenuOpen]);

  return (
    <div
      ref={itemRef}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      className={`group relative flex items-center h-10 px-0 my-0.5 rounded-xl text-sm transition-[color,background-color,border-color,opacity,transform] duration-150 ease-out cursor-pointer overflow-hidden whitespace-nowrap ${flashing ? 'animate-flash-link ' : ''}${
        isActive
          ? 'bg-surface-raised font-semibold text-foreground shadow-xs'
          : 'hover:bg-surface-raised/60 text-foreground-secondary hover:text-foreground'
      }`}
      title={isOpen ? shownTitle : undefined}
    >
      {/* Icon Slot */}
      <div onClick={onSelect} className="w-12 h-10 flex items-center justify-center shrink-0">
        <MessageSquare className={`w-4 h-4 shrink-0 transition-colors ${isActive ? 'text-accent-primary' : 'text-foreground-muted group-hover:text-foreground'}`} />
      </div>

      {/* Text Slot & Actions */}
      <div className={`flex items-center justify-between flex-1 overflow-hidden pr-2 whitespace-nowrap transition-[opacity,visibility] duration-300 ease-in-out ${isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none invisible'}`}>
        {isEditing ? (
          <input
            type="text"
            value={editingTitle}
            onChange={(e) => setEditingTitle(e.target.value)}
            onFocus={(e) => e.target.select()}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onSaveRename();
              if (e.key === 'Escape') {
                if (onCancelRename) onCancelRename();
                else setEditingTitle(shownTitle);
              }
            }}
            onBlur={onSaveRename}
            autoFocus
            className="w-full text-xs px-1.5 py-0.5 border border-accent-primary rounded bg-surface text-foreground outline-none select-all"
          />
        ) : (
          <span
            onClick={onSelect}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSelect();
              }
            }}
            role="button"
            tabIndex={isOpen ? 0 : -1}
            aria-current={isActive ? 'true' : undefined}
            title={shownTitle}
            className={`truncate block max-w-full text-left text-xs flex-1 pr-1 rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary ${
              isActive ? 'text-foreground font-semibold' : 'text-foreground-secondary group-hover:text-foreground'
            }`}
          >
            {shownTitle}
          </span>
        )}

        <div className="flex items-center gap-1 shrink-0">
          {session.isPinned && <Pin className="w-3 h-3 text-accent-planner shrink-0 fill-current" />}
          <button
            ref={buttonRef}
            type="button"
            onClick={handleToggleMenu}
            className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100 p-1 hover:bg-surface-overlay rounded-lg transition-opacity duration-200 ease-out cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
            title={t(lang, 'sidebar.options')}
            aria-label={t(lang, 'sidebar.options')}
            aria-haspopup="menu"
            aria-expanded={isMenuOpen}
          >
            <MoreVertical className="w-3.5 h-3.5 text-foreground-muted" />
          </button>
        </div>
      </div>

      {/* Portal Dropdown Menu */}
      {isMenuOpen && menuPos && typeof document !== 'undefined' && createPortal(
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'fixed',
            top: `${menuPos.top}px`,
            right: `${menuPos.right}px`,
          }}
          className="z-menu bg-surface border border-border-strong rounded-xl shadow-enterprise p-1.5 w-48 text-xs space-y-1 whitespace-nowrap animate-fade-in-scale"
        >
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onTogglePin(); setMenuOpen(false); }}
            className="flex items-center gap-2.5 w-full px-2.5 py-2 hover:bg-surface-raised text-foreground-secondary rounded-lg cursor-pointer transition-colors"
          >
            <Pin className="w-3.5 h-3.5 text-foreground-muted shrink-0" />
            <span>{session.isPinned ? t(lang, 'sidebar.unpin') : t(lang, 'sidebar.pin')}</span>
          </button>

          {onRename && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onRename(); }}
              className="flex items-center gap-2.5 w-full px-2.5 py-2 hover:bg-surface-raised text-foreground-secondary rounded-lg cursor-pointer transition-colors"
            >
              <Edit3 className="w-3.5 h-3.5 text-foreground-muted shrink-0" />
              <span>{t(lang, 'sidebar.rename')}</span>
            </button>
          )}

          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onDelete(); setMenuOpen(false); }}
            className="flex items-center gap-2.5 w-full px-2.5 py-2 hover:bg-accent-error/10 text-accent-error rounded-lg font-medium cursor-pointer transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5 shrink-0" />
            <span>{t(lang, 'sidebar.delete')}</span>
          </button>
        </div>,
        document.body
      )}

      {/* Floating Tooltip in Collapsed Mode */}
      {!isOpen && isHovered && tooltipPos && typeof document !== 'undefined' && createPortal(
        <div
          style={{
            position: 'fixed',
            top: `${tooltipPos.top}px`,
            left: `${tooltipPos.left}px`,
          }}
          className="z-menu bg-surface border border-border-strong rounded-xl shadow-lg p-2.5 w-60 pointer-events-none select-none animate-fade-in-scale"
        >
          <p className="text-xs font-semibold text-foreground truncate">{shownTitle}</p>
          <div className="flex items-center justify-between text-xs text-foreground-muted mt-1.5 font-mono">
            <span>{new Date(session.updatedAt).toLocaleDateString(lang === 'vi' ? 'vi-VN' : 'en-GB')}</span>
            {session.isPinned && <span className="text-accent-planner font-semibold">{t(lang, 'sidebar.pinned')}</span>}
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}
