'use client';

import React, { useState } from 'react';
import { Search, MessageSquare, X } from 'lucide-react';
import { ChatSession } from './Sidebar';

interface SearchViewProps {
  sessions: ChatSession[];
  onSelectSession: (id: string) => void;
  onClose: () => void;
}

export function SearchView({ 
  sessions, 
  onSelectSession, 
  onClose 
}: SearchViewProps) {
  const [query, setQuery] = useState('');

  const filtered = sessions.filter(s => 
    s.title.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div className="flex-1 flex flex-col h-full min-h-0 bg-white items-center pt-16 px-6 overflow-y-auto animate-in fade-in duration-200">
      
      {/* Container Ô Tìm Kiếm Trung Tâm */}
      <div className="w-full max-w-2xl space-y-8">
        
        {/* Input Bar Lớn Chuẩn Gemini */}
        <div className="relative flex items-center bg-slate-100/80 hover:bg-slate-100 focus-within:bg-white border border-slate-200/80 rounded-full px-5 py-3.5 shadow-xs focus-within:shadow-md focus-within:ring-2 focus-within:ring-blue-100 transition-all">
          <Search className="w-5 h-5 text-slate-500 mr-3 shrink-0"/>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
            autoFocus
            className="w-full bg-transparent text-slate-800 placeholder-slate-400 text-base focus:outline-none"
          />
          {query && (
            <button 
              type="button"
              onClick={() => setQuery('')} 
              className="p-1 hover:bg-slate-200 rounded-full text-slate-400 cursor-pointer"
            >
              <X className="w-4 h-4"/>
            </button>
          )}
        </div>

        {/* Danh Sách Kết Quả Search / Recent Sessions */}
        <div className="space-y-3">
          <div className="text-sm font-medium text-slate-500 px-2 select-none">
            Recent
          </div>

          <div className="space-y-1">
            {filtered.length > 0 ? (
              filtered.map((session) => (
                <div
                  key={session.id}
                  onClick={() => {
                    onSelectSession(session.id);
                    onClose();
                  }}
                  className="flex items-center justify-between p-3.5 rounded-2xl hover:bg-slate-100/80 cursor-pointer transition-all group"
                >
                  {/* Tiêu đề bên trái */}
                  <div className="flex items-center gap-3 text-slate-800 font-medium text-sm group-hover:text-blue-900 truncate pr-4">
                    <MessageSquare className="w-4 h-4 text-slate-400 shrink-0 group-hover:text-blue-600"/>
                    <span className="truncate max-w-md">{session.title}</span>
                  </div>

                  {/* Ngày tháng bên phải */}
                  <span className="text-xs text-slate-400 font-normal shrink-0">
                    {session.updatedAt ? new Date(session.updatedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : 'Today'}
                  </span>
                </div>
              ))
            ) : (
              <div className="text-center py-12 text-slate-400 text-sm">
                Không tìm thấy cuộc trò chuyện nào phù hợp.
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
