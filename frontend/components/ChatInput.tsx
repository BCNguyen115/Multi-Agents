'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Plus, Send, ChevronDown, Cloud, Database, Globe, FileSpreadsheet, FileText, X, Loader2 } from 'lucide-react';

interface ChatInputProps {
  selectedAgent: string;
  onSelectAgent: (agentId: string) => void;
  onSendMessage: (text: string, file: File | null) => void;
  isSending?: boolean;
  attachedFile?: File | null;
  onFileSelect?: (file: File | null) => void;
}

export function ChatInput({
  selectedAgent,
  onSelectAgent,
  onSendMessage,
  isSending,
  attachedFile = null,
  onFileSelect,
}: ChatInputProps) {
  const [text, setText] = useState("");
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const agents = [
    { id: 'RAG Agent', name: 'RAG Agent', icon: Cloud, desc: 'Tra cứu hợp đồng & NDA' },
    { id: '📊 Data Agent', name: 'Data Agent', icon: Database, desc: 'Phân tích CSV & Dashboard' },
    { id: '🌐 Search Agent', name: 'Search Agent', icon: Globe, desc: 'Tìm kiếm Web real-time' },
  ];

  const currentAgent = agents.find(a => a.id === selectedAgent || selectedAgent.includes(a.name.split(' ')[0])) || agents[0];
  const isExpanded = text.length > 0 || attachedFile !== null || text.includes('\n');

  // Auto-resize Textarea height & maintain single mounted focus
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const newHeight = isExpanded ? Math.min(textareaRef.current.scrollHeight, 160) : 24;
      textareaRef.current.style.height = `${newHeight}px`;
    }
  }, [text, isExpanded]);

  // Focus textarea khi có file được đính kèm (cả từ Nút + hoặc Drag & Drop)
  useEffect(() => {
    if (attachedFile && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [attachedFile]);

  const handleSend = () => {
    if (text.trim() || attachedFile) {
      onSendMessage(text, attachedFile);
      setText("");
      setIsDropdownOpen(false);
      if (textareaRef.current) {
        textareaRef.current.style.height = '24px';
      }
    }
  };

  const getFileIcon = (fileName?: string) => {
    if (!fileName) return <FileSpreadsheet className="w-4 h-4 text-[#005697] dark:text-blue-400" />;
    const lower = fileName.toLowerCase();
    if (lower.endsWith('.csv') || lower.endsWith('.xlsx') || lower.endsWith('.xls')) {
      return <FileSpreadsheet className="w-4 h-4 text-[#005697] dark:text-blue-400" />;
    }
    return <FileText className="w-4 h-4 text-[#005697] dark:text-blue-400" />;
  };

  return (
    <div className="mx-auto max-w-5xl w-full px-4">
      {/* Hidden File Input */}
      <input 
        type="file" 
        ref={fileInputRef} 
        accept=".csv,.xlsx,.xls,.pdf,.docx,.doc,.txt" 
        className="hidden" 
        onChange={(e) => {
          if (e.target.files?.[0]) {
            onFileSelect?.(e.target.files[0]);
          }
          e.target.value = '';
        }} 
      />

      {/* CONTAINER KHUNG CHAT DYNAMIC */}
      <div 
        className={`bg-white/95 dark:bg-slate-800/95 backdrop-blur-md border border-slate-200/90 dark:border-slate-700/90 shadow-lg shadow-slate-200/40 dark:shadow-slate-950/50 transition-all duration-300 ease-in-out focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100 dark:focus-within:ring-blue-900/40 ${
          isExpanded 
            ? 'rounded-3xl p-3.5 flex flex-col gap-3' 
            : 'rounded-full px-4 py-2.5 flex items-center gap-2 min-h-[54px]'
        }`}
      >
        {/* PREVIEW FILE CHIP (Hiển thị đồng nhất cho cả nút + và Drag & Drop) */}
        {attachedFile && (
          <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 dark:bg-blue-950/60 border border-blue-200 dark:border-blue-800 rounded-xl text-xs w-fit text-blue-900 dark:text-blue-200 font-medium animate-in fade-in">
            {getFileIcon(attachedFile.name)}
            <span className="truncate max-w-xs font-semibold">{attachedFile.name}</span>
            <span className="text-slate-400 dark:text-slate-500">({(attachedFile.size / 1024).toFixed(0)}KB)</span>
            <button 
              type="button" 
              onClick={() => onFileSelect?.(null)} 
              className="hover:text-red-500 ml-1 cursor-pointer transition-colors p-0.5"
              title="Gỡ file đính kèm"
            >
              <X className="w-3.5 h-3.5"/>
            </button>
          </div>
        )}

        {/* HÀNG TRÊN: TEXTAREA DUY NHẤT MOUNTED KHÔNG HỦY DOM NODE */}
        <div className={`w-full flex ${isExpanded ? 'flex-col gap-2' : 'items-center justify-between gap-2'}`}>
          
          {/* Nút + bên trái (khi chưa Expand) */}
          {!isExpanded && (
            <button 
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-full text-slate-500 dark:text-slate-400 hover:text-[#005697] dark:hover:text-blue-400 transition-colors shrink-0 cursor-pointer"
              title="Đính kèm file (.csv, .xlsx, .pdf, .docx)"
            >
              <Plus className="w-5 h-5"/>
            </button>
          )}

          {/* TEXTAREA MOUNTED DUY NHẤT */}
          <div className="flex-1 w-full flex items-center">
            <textarea
              ref={textareaRef}
              rows={1}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={attachedFile ? "Nhập câu hỏi hoặc đúp chuột gửi để phân tích file..." : "Nhập yêu cầu phân tích dữ liệu hoặc đính kèm file CSV..."}
              className="w-full bg-transparent text-slate-800 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 text-sm focus:outline-none resize-none leading-relaxed overflow-y-auto"
              style={{ height: '24px', minHeight: '24px' }}
            />
          </div>

          {/* Cụm Nút bên phải (khi chưa Expand) */}
          {!isExpanded && (
            <div className="flex items-center gap-2 shrink-0 relative">
              <AgentDropdown
                agents={agents}
                currentAgent={currentAgent}
                selectedAgent={selectedAgent}
                isOpen={isDropdownOpen}
                setIsOpen={setIsDropdownOpen}
                onSelect={(id: string) => {
                  onSelectAgent(id);
                  setIsDropdownOpen(false);
                }}
              />
              <button 
                type="button"
                disabled={isSending || (!text.trim() && !attachedFile)}
                onClick={handleSend}
                className="bg-[#005697] hover:bg-[#004070] text-white p-2 rounded-full shadow-sm transition-all shrink-0 active:scale-95 disabled:opacity-50 cursor-pointer"
              >
                {isSending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4"/>}
              </button>
            </div>
          )}

        </div>

        {/* HÀNG CÔNG CỤ ĐÁY (KHU VỰC KHI ĐÃ EXPAND) */}
        {isExpanded && (
          <div className="flex items-center justify-between pt-2 border-t border-slate-100 dark:border-slate-700/80 animate-in fade-in duration-150">
            <button 
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-full text-slate-500 dark:text-slate-400 hover:text-[#005697] dark:hover:text-blue-400 transition-colors cursor-pointer"
              title="Đính kèm file (.csv, .xlsx, .pdf, .docx)"
            >
              <Plus className="w-5 h-5"/>
            </button>

            <div className="flex items-center gap-2 relative">
              <AgentDropdown
                agents={agents}
                currentAgent={currentAgent}
                selectedAgent={selectedAgent}
                isOpen={isDropdownOpen}
                setIsOpen={setIsDropdownOpen}
                onSelect={(id: string) => {
                  onSelectAgent(id);
                  setIsDropdownOpen(false);
                }}
              />
              <button 
                type="button"
                disabled={isSending || (!text.trim() && !attachedFile)}
                onClick={handleSend}
                className="bg-[#005697] hover:bg-[#004070] text-white p-2.5 rounded-2xl shadow-md transition-all shrink-0 active:scale-95 disabled:opacity-50 cursor-pointer"
              >
                {isSending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4"/>}
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}

// Sub-component Dropdown Selector
function AgentDropdown({ currentAgent, agents, selectedAgent, onSelect, isOpen, setIsOpen }: any) {
  const CurrentIcon = currentAgent.icon;
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1.5 px-3 py-1 bg-slate-100 dark:bg-slate-700/80 hover:bg-slate-200/80 dark:hover:bg-slate-700 border border-slate-200/80 dark:border-slate-600/80 rounded-full text-xs font-semibold text-slate-700 dark:text-slate-200 transition-all cursor-pointer"
      >
        <CurrentIcon className="w-3.5 h-3.5 text-[#005697] dark:text-blue-400"/>
        <span>{currentAgent.name}</span>
        <ChevronDown className={`w-3.5 h-3.5 text-slate-400 dark:text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className="absolute right-0 bottom-10 mb-2 w-56 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-xl p-1.5 z-50 text-xs animate-in fade-in zoom-in-95">
          <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500 border-b border-slate-100 dark:border-slate-700 select-none">
            Chọn Agent xử lý:
          </div>
          {agents.map((agent: any) => {
            const Icon = agent.icon;
            const isSelected = selectedAgent === agent.id || selectedAgent.includes(agent.name.split(' ')[0]);
            return (
              <button
                key={agent.id}
                type="button"
                onClick={() => {
                  onSelect(agent.id);
                  setIsOpen(false);
                }}
                className={`flex items-start gap-2.5 w-full p-2.5 rounded-xl transition-all text-left cursor-pointer ${
                  isSelected ? 'bg-blue-50 dark:bg-blue-950/60 text-[#005697] dark:text-blue-300 font-semibold' : 'hover:bg-slate-100 dark:hover:bg-slate-700/80 text-slate-700 dark:text-slate-200'
                }`}
              >
                <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${isSelected ? 'text-[#005697] dark:text-blue-400' : 'text-slate-400'}`} />
                <div>
                  <div className="font-medium">{agent.name}</div>
                  <div className="text-[10px] text-slate-400 dark:text-slate-500 font-normal">{agent.desc}</div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
