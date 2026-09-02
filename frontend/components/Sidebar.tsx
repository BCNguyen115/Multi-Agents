'use client';

import React, { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { PanelLeft, PenSquare, Search, Pin, MoreVertical, Trash2, Edit3, MessageSquare } from 'lucide-react';
import { FptLogo } from './ui/FptLogo';

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
  onDeleteSession: (id: string) => void;
  onTogglePin: (id: string) => void;
  onRenameSession?: (id: string, newTitle: string) => void;
  onOpenSearch?: () => void;
}

export function Sidebar({ 
  sessions = [], 
  activeSessionId, 
  onSelectSession, 
  onNewChat, 
  onOpenSearch,
  onDeleteSession, 
  onTogglePin,
  onRenameSession,
}: SidebarProps) {
  const [isOpen, setIsOpen] = useState(true);
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');

  const pinnedSessions = sessions.filter((s: ChatSession) => s.isPinned);
  const recentSessions = sessions.filter((s: ChatSession) => !s.isPinned);

  const handleStartRename = (session: ChatSession) => {
    setEditingSessionId(session.id);
    setEditingTitle(session.title);
    setActiveMenuId(null);
  };

  const handleSaveRename = (id: string) => {
    if (editingTitle.trim() && onRenameSession) {
      onRenameSession(id, editingTitle.trim());
    }
    setEditingSessionId(null);
  };

  return (
    <aside 
      className={`
        h-screen bg-[#F8F9FA] dark:bg-slate-900 
        border-r border-slate-200/80 dark:border-slate-800 
        transition-all duration-300 ease-in-out transform-gpu will-change-[width]
        flex flex-col shrink-0 overflow-hidden select-none relative z-30
        ${isOpen ? 'w-64' : 'w-16'}
      `}
    >
      {/* 1. SIDEBAR HEADER (FIXED ICON COLUMN W-12) */}
      <div className="h-14 flex items-center px-2 border-b border-slate-200/60 dark:border-slate-800/60 shrink-0 relative overflow-hidden whitespace-nowrap">
        {/* Cột Icon Logo cố định - Luôn nằm im vị trí này */}
        <div className="w-12 h-12 flex items-center justify-center shrink-0 relative group cursor-pointer">
          <FptLogo 
            className={`h-6 w-auto object-contain transition-opacity duration-200 ease-out ${!isOpen ? 'group-hover:opacity-0' : ''}`}
          />
          
          {/* Khi Collapsed & Hover vào Logo: Hiển thị Nút Toggle tại đúng tâm Logo */}
          {!isOpen && (
            <button 
              type="button"
              onClick={() => setIsOpen(true)}
              className="absolute inset-0 m-auto w-8 h-8 flex items-center justify-center rounded-lg bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700 text-[#005697] dark:text-blue-400 opacity-0 group-hover:opacity-100 transition-opacity duration-200 ease-out shadow-sm cursor-pointer"
              title="Mở rộng Sidebar"
            >
              <PanelLeft className="w-5 h-5"/>
            </button>
          )}
        </div>

        {/* Phần Text Thương hiệu & Nút Toggle khi Sidebar MỞ */}
        <div className={`flex items-center justify-between flex-1 overflow-hidden whitespace-nowrap transition-all duration-300 ease-in-out ${isOpen ? 'opacity-100 w-auto ml-1' : 'opacity-0 w-0 pointer-events-none'}`}>
          <span className="font-bold text-slate-800 dark:text-white whitespace-nowrap text-base">
            FPT<span className="text-[#005697] dark:text-blue-400">AgentHub</span>
          </span>
          <button 
            type="button"
            onClick={() => setIsOpen(false)}
            className="p-1.5 rounded-lg hover:bg-slate-200/70 dark:hover:bg-slate-800 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 transition-colors duration-200 ease-out cursor-pointer shrink-0"
            title="Thu gọn Sidebar"
          >
            <PanelLeft className="w-5 h-5"/>
          </button>
        </div>
      </div>

      {/* 2. CHỨC NĂNG CHÍNH (NEW CHAT & SEARCH CHATS - FIXED ICON COLUMN W-12) */}
      <div className="py-2.5 space-y-1 border-b border-slate-200/40 dark:border-slate-800 px-2 shrink-0 overflow-hidden whitespace-nowrap">
        {/* Nút New Chat */}
        <button
          type="button"
          onClick={onNewChat}
          className="flex items-center h-10 px-0 rounded-xl hover:bg-slate-200/60 dark:hover:bg-slate-800/60 w-full transition-colors duration-200 ease-out group cursor-pointer overflow-hidden whitespace-nowrap"
          title="New chat"
        >
          {/* Icon Slot Cố Định */}
          <div className="w-12 h-10 flex items-center justify-center shrink-0">
            <PenSquare className="w-5 h-5 text-slate-700 dark:text-slate-300"/>
          </div>
          
          {/* Text Slot - Chỉ ẩn/hiện opacity, không đẩy Icon */}
          <span className={`text-sm font-medium text-slate-700 dark:text-slate-200 whitespace-nowrap transition-all duration-300 ease-in-out ${isOpen ? 'opacity-100 w-auto ml-1' : 'opacity-0 w-0 pointer-events-none overflow-hidden'}`}>
            New chat
          </span>
        </button>

        {/* Nút Search Chats */}
        <button
          type="button"
          onClick={onOpenSearch}
          className="flex items-center h-10 px-0 rounded-xl hover:bg-slate-200/60 dark:hover:bg-slate-800/60 w-full transition-colors duration-200 ease-out group cursor-pointer overflow-hidden whitespace-nowrap"
          title="Search chats"
        >
          {/* Icon Slot Cố Định */}
          <div className="w-12 h-10 flex items-center justify-center shrink-0">
            <Search className="w-5 h-5 text-slate-700 dark:text-slate-300"/>
          </div>
          
          {/* Text Slot - Chỉ ẩn/hiện opacity, không đẩy Icon */}
          <span className={`text-sm font-medium text-slate-700 dark:text-slate-200 whitespace-nowrap transition-all duration-300 ease-in-out ${isOpen ? 'opacity-100 w-auto ml-1' : 'opacity-0 w-0 pointer-events-none overflow-hidden'}`}>
            Search chats
          </span>
        </button>
      </div>

      {/* 3. DANH SÁCH LỊCH SỬ CHAT (RECENTS & PINNED - FIXED ICON COLUMN W-12) */}
      <div className="flex-1 overflow-y-auto px-2 py-3 space-y-4 overflow-x-hidden whitespace-nowrap">
        {/* Pinned Section */}
        {pinnedSessions.length > 0 && (
          <div>
            <div className={`px-3 text-[11px] font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1 flex items-center justify-between select-none whitespace-nowrap transition-all duration-300 ease-in-out ${isOpen ? 'opacity-100 w-auto' : 'opacity-0 w-0 overflow-hidden'}`}>
              <span>Pinned</span>
              <Pin className="w-3 h-3 text-slate-400 dark:text-slate-500" />
            </div>
            {pinnedSessions.map((session: ChatSession) => (
              <ChatItem 
                key={session.id}
                session={session}
                isOpen={isOpen}
                isActive={session.id === activeSessionId}
                onSelect={() => onSelectSession(session.id)}
                onDelete={() => onDeleteSession(session.id)}
                onTogglePin={() => onTogglePin(session.id)}
                onRename={() => handleStartRename(session)}
                isEditing={editingSessionId === session.id}
                editingTitle={editingTitle}
                setEditingTitle={setEditingTitle}
                onSaveRename={() => handleSaveRename(session.id)}
                isMenuOpen={activeMenuId === session.id}
                setMenuOpen={(open: boolean) => setActiveMenuId(open ? session.id : null)}
              />
            ))}
          </div>
        )}

        {/* Recents Section */}
        <div>
          <div className={`px-3 text-[11px] font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1 select-none whitespace-nowrap transition-all duration-300 ease-in-out ${isOpen ? 'opacity-100 w-auto' : 'opacity-0 w-0 overflow-hidden'}`}>
            Recents
          </div>
          {recentSessions.length > 0 ? (
            recentSessions.map((session: ChatSession) => (
              <ChatItem 
                key={session.id}
                session={session}
                isOpen={isOpen}
                isActive={session.id === activeSessionId}
                onSelect={() => onSelectSession(session.id)}
                onDelete={() => onDeleteSession(session.id)}
                onTogglePin={() => onTogglePin(session.id)}
                onRename={() => handleStartRename(session)}
                isEditing={editingSessionId === session.id}
                editingTitle={editingTitle}
                setEditingTitle={setEditingTitle}
                onSaveRename={() => handleSaveRename(session.id)}
                isMenuOpen={activeMenuId === session.id}
                setMenuOpen={(open: boolean) => setActiveMenuId(open ? session.id : null)}
              />
            ))
          ) : (
            isOpen && (
              <div className="px-3 py-2 text-xs text-slate-400 dark:text-slate-500 italic select-none whitespace-nowrap">
                Chưa có cuộc trò chuyện nào
              </div>
            )
          )}
        </div>
      </div>
    </aside>
  );
}

// Sub-component Chat Item với React Portal Dropdown Menu chống bị cắt xén
function ChatItem({ 
  session, 
  isOpen,
  isActive, 
  onSelect, 
  onDelete, 
  onTogglePin, 
  onRename,
  isEditing,
  editingTitle,
  setEditingTitle,
  onSaveRename,
  isMenuOpen, 
  setMenuOpen 
}: any) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; right: number } | null>(null);

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

  // Tự động đóng Menu khi click ra ngoài hoặc khi cuộn danh sách
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
      className={`group relative flex items-center h-10 px-0 my-0.5 rounded-xl text-sm transition-colors duration-200 ease-out cursor-pointer overflow-hidden whitespace-nowrap ${
        isActive 
          ? 'bg-slate-200/80 dark:bg-slate-800 font-semibold text-slate-900 dark:text-slate-100 shadow-2xs' 
          : 'hover:bg-slate-200/50 dark:hover:bg-slate-800/60 text-slate-700 dark:text-slate-300'
      }`}
      title={!isOpen ? session.title : undefined}
    >
      {/* Icon Slot Cố Định w-12 h-10 */}
      <div onClick={onSelect} className="w-12 h-10 flex items-center justify-center shrink-0">
        <MessageSquare className="w-4 h-4 text-slate-400 dark:text-slate-500 shrink-0"/>
      </div>

      {/* Text Slot & Actions - Chỉ ẩn/hiện opacity */}
      <div className={`flex items-center justify-between flex-1 overflow-hidden pr-2 whitespace-nowrap transition-all duration-300 ease-in-out ${isOpen ? 'opacity-100 w-auto' : 'opacity-0 w-0 pointer-events-none'}`}>
        {isEditing ? (
          <input
            type="text"
            value={editingTitle}
            onChange={(e) => setEditingTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onSaveRename();
              if (e.key === 'Escape') setEditingTitle(session.title);
            }}
            onBlur={onSaveRename}
            autoFocus
            className="w-full text-xs px-1.5 py-0.5 border border-blue-400 rounded bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 outline-none"
          />
        ) : (
          <span onClick={onSelect} className="truncate text-xs flex-1 pr-1">{session.title}</span>
        )}

        <div className="flex items-center gap-1 shrink-0">
          {session.isPinned && <Pin className="w-3 h-3 text-[#F37021] shrink-0 fill-[#F37021]"/>}
          <button 
            ref={buttonRef}
            type="button"
            onClick={handleToggleMenu}
            className="opacity-0 group-hover:opacity-100 p-1 hover:bg-slate-300/50 dark:hover:bg-slate-700 rounded-lg transition-opacity duration-200 ease-out cursor-pointer"
            title="Tùy chọn"
          >
            <MoreVertical className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400"/>
          </button>
        </div>
      </div>

      {/* BẮT BUỘC DÙNG PORTAL RENDER THẲNG VÀO DOCUMENT.BODY ĐỂ NỔI LÊN TRÊN HẲN OVERFLOW-HIDDEN */}
      {isMenuOpen && menuPos && typeof document !== 'undefined' && createPortal(
        <div 
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'fixed',
            top: `${menuPos.top}px`,
            right: `${menuPos.right}px`,
            zIndex: 9999,
          }}
          className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-2xl p-1.5 w-48 text-xs space-y-1 whitespace-nowrap animate-in fade-in duration-150"
        >
          {/* 1. Ghim cuộc trò chuyện (Pin / Unpin) */}
          <button 
            type="button"
            onClick={(e) => { e.stopPropagation(); onTogglePin(); setMenuOpen(false); }}
            className="flex items-center gap-2.5 w-full px-2.5 py-2 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 rounded-lg cursor-pointer transition-colors"
          >
            <Pin className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400 shrink-0"/>
            <span>{session.isPinned ? 'Bỏ ghim' : 'Ghim cuộc trò chuyện'}</span>
          </button>

          {/* 2. Đổi tên (Rename) */}
          {onRename && (
            <button 
              type="button"
              onClick={(e) => { e.stopPropagation(); onRename(); }}
              className="flex items-center gap-2.5 w-full px-2.5 py-2 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 rounded-lg cursor-pointer transition-colors"
            >
              <Edit3 className="w-3.5 h-3.5 text-slate-500 dark:text-slate-400 shrink-0"/>
              <span>Đổi tên</span>
            </button>
          )}

          {/* 3. Xóa cuộc trò chuyện (Delete) */}
          <button 
            type="button"
            onClick={(e) => { e.stopPropagation(); onDelete(); setMenuOpen(false); }}
            className="flex items-center gap-2.5 w-full px-2.5 py-2 hover:bg-red-50 dark:hover:bg-red-950/40 text-red-600 dark:text-red-400 rounded-lg font-medium cursor-pointer transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5 text-red-500 dark:text-red-400 shrink-0"/>
            <span>Xóa cuộc trò chuyện</span>
          </button>
        </div>,
        document.body
      )}
    </div>
  );
}
