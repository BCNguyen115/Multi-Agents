'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Plus, Send, ChevronDown, Cloud, Database, Globe, FileSpreadsheet, FileText, X, Loader2 } from 'lucide-react';
import { ACCEPT_ATTRIBUTE, isTabularFile } from '../lib/fileTypes';
import { t, useLang } from '../lib/i18n';

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
  const [lang] = useLang();
  const [text, setText] = useState("");
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const agents = [
    { id: 'RAG Agent', name: 'RAG Agent', icon: Cloud, desc: t(lang, 'agent.ragDesc') },
    { id: 'Data Agent', name: 'Data Agent', icon: Database, desc: t(lang, 'agent.dataDesc') },
    { id: 'Search Agent', name: 'Search Agent', icon: Globe, desc: t(lang, 'agent.searchDesc') },
  ];

  const currentAgent = agents.find(a => a.id === selectedAgent) || agents[0];
  const isExpanded = text.length > 0 || attachedFile !== null || text.includes('\n');

  // Auto-resize Textarea (up to 200px with smooth scroll)
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      const newHeight = isExpanded ? Math.min(textareaRef.current.scrollHeight, 200) : 24;
      textareaRef.current.style.height = `${newHeight}px`;
    }
  }, [text, isExpanded]);

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
    if (!fileName) return <FileSpreadsheet className="w-4 h-4 text-accent-primary" />;
    const lower = fileName.toLowerCase();
    if (isTabularFile(lower)) {
      return <FileSpreadsheet className="w-4 h-4 text-accent-primary" />;
    }
    return <FileText className="w-4 h-4 text-accent-primary" />;
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  return (
    <div className="mx-auto max-w-5xl w-full px-4" data-testid="chat-input">
      {/* Hidden File Input */}
      <input
        type="file"
        ref={fileInputRef}
        accept={ACCEPT_ATTRIBUTE}
        className="hidden"
        onChange={(e) => {
          if (e.target.files?.[0]) {
            onFileSelect?.(e.target.files[0]);
          }
          e.target.value = '';
        }}
      />

      {/* CHAT INPUT CONTAINER */}
      <div
        className={`bg-surface border border-border shadow-md text-foreground transition-all duration-200 ease-out focus-within:border-accent-primary focus-within:ring-2 focus-within:ring-accent-primary/20 ${
          isExpanded
            ? 'rounded-2xl p-4 flex flex-col gap-3'
            : 'rounded-full px-4 py-2 flex items-center gap-2 min-h-14'
        }`}
      >
        {/* File Preview Chip */}
        {attachedFile && (
          <div className="flex items-center gap-2 px-3 py-1.5 bg-accent-primary/8 border border-accent-primary/15 rounded-lg text-xs w-fit text-foreground font-medium animate-fade-in" data-testid="csv-upload-dropzone">
            {getFileIcon(attachedFile.name)}
            <span className="truncate max-w-xs font-semibold">{attachedFile.name}</span>
            <span className="text-foreground-muted font-mono tabular-nums">({formatFileSize(attachedFile.size)})</span>
            <button
              type="button"
              onClick={() => onFileSelect?.(null)}
              className="hover:text-accent-error ml-1 cursor-pointer transition-colors p-0.5 rounded focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-primary/40"
              title={t(lang, 'input.removeFile')}
              aria-label={t(lang, 'input.removeFile')}
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Main Row: Textarea + Actions */}
        <div className={`w-full flex ${isExpanded ? 'flex-col gap-2' : 'items-center justify-between gap-2'}`}>

          {/* Plus Button (collapsed mode) */}
          {!isExpanded && (
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="p-1.5 hover:bg-surface-raised rounded-full text-foreground-muted hover:text-accent-primary transition-colors shrink-0 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
              title={t(lang, 'input.attachFileTypes', { types: '.csv, .xlsx, .pdf, .docx, .pptx, .txt, .md' })}
              aria-label={t(lang, 'input.attachFile')}
            >
              <Plus className="w-5 h-5" />
            </button>
          )}

          {/* TEXTAREA */}
          <div className="flex-1 w-full flex items-center">
            <textarea
              ref={textareaRef}
              rows={1}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if ((e.key === 'Enter' && !e.shiftKey) || (e.key === 'Enter' && (e.metaKey || e.ctrlKey))) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              aria-label={t(lang, 'input.placeholderDefault')}
              placeholder={
                attachedFile
                  ? isTabularFile(attachedFile.name)
                    ? t(lang, 'input.placeholderTable')
                    : t(lang, 'input.placeholderDocument')
                  : t(lang, 'input.placeholderDefault')
              }
              className="w-full bg-transparent text-foreground placeholder-foreground-muted text-sm focus:outline-none resize-none leading-relaxed overflow-y-auto"
              style={{ height: '24px', minHeight: '24px' }}
            />
          </div>

          {/* Right Actions (collapsed mode) */}
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
                data-testid="send-button"
                disabled={isSending || (!text.trim() && !attachedFile)}
                onClick={handleSend}
                className="w-9 h-9 flex items-center justify-center bg-accent-primary hover:bg-accent-primary-hover text-white rounded-full shadow-xs transition-all duration-150 shrink-0 active:scale-95 disabled:opacity-40 disabled:hover:bg-accent-primary disabled:active:scale-100 disabled:cursor-not-allowed cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
                title={text.trim() || attachedFile ? t(lang, 'input.sendTitle') : t(lang, 'input.sendEmpty')}
                aria-label={t(lang, 'input.sendTitle')}
              >
                {isSending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </div>
          )}
        </div>

        {/* Bottom Toolbar (expanded mode) */}
        {isExpanded && (
          <div className="flex items-center justify-between pt-2 border-t border-border animate-fade-in">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="p-1.5 hover:bg-surface-raised rounded-full text-foreground-muted hover:text-accent-primary transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
                title={t(lang, 'input.attachFile')}
                aria-label={t(lang, 'input.attachFile')}
              >
                <Plus className="w-5 h-5" />
              </button>
              <span className="text-xs text-foreground-muted font-mono hidden sm:inline">
                {t(lang, 'input.keys')}
              </span>
            </div>

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
                data-testid="send-button"
                disabled={isSending || (!text.trim() && !attachedFile)}
                onClick={handleSend}
                className="w-9 h-9 flex items-center justify-center bg-accent-primary hover:bg-accent-primary-hover text-white rounded-full shadow-xs transition-all duration-150 shrink-0 active:scale-95 disabled:opacity-40 disabled:hover:bg-accent-primary disabled:active:scale-100 disabled:cursor-not-allowed cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
                title={text.trim() || attachedFile ? t(lang, 'input.sendTitle') : t(lang, 'input.sendEmpty')}
                aria-label={t(lang, 'input.sendTitle')}
              >
                {isSending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Agent Dropdown Selector with Click-outside and Escape key accessibility
function AgentDropdown({ currentAgent, agents, selectedAgent, onSelect, isOpen, setIsOpen }: {
  currentAgent: { id: string; name: string; icon: React.ElementType; desc: string };
  agents: { id: string; name: string; icon: React.ElementType; desc: string }[];
  selectedAgent: string;
  onSelect: (id: string) => void;
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
}) {
  const [lang] = useLang();
  const CurrentIcon = currentAgent.icon;
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, setIsOpen]);

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1.5 px-3 py-1 bg-surface-raised hover:bg-surface-overlay border border-border rounded-full text-xs font-semibold text-foreground-secondary transition-all cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <CurrentIcon className="w-3.5 h-3.5 text-accent-primary" />
        <span>{currentAgent.name}</span>
        <ChevronDown className={`w-3.5 h-3.5 text-foreground-muted transition-transform duration-150 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className="absolute right-0 bottom-10 mb-2 w-56 bg-surface border border-border-strong rounded-xl shadow-enterprise p-1.5 z-50 text-xs animate-fade-in-scale">
          <div className="px-3 py-1.5 text-xs font-bold uppercase tracking-wider text-foreground-muted border-b border-border select-none">
            {t(lang, 'agent.choose')}
          </div>
          <div className="mt-1 space-y-0.5" role="listbox">
            {agents.map((agent) => {
              const Icon = agent.icon;
              const isSelected = selectedAgent === agent.id || selectedAgent.includes(agent.name.split(' ')[0]);
              return (
                <button
                  key={agent.id}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => {
                    onSelect(agent.id);
                    setIsOpen(false);
                  }}
                  className={`flex items-start gap-2.5 w-full p-2.5 rounded-lg transition-all text-left cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40 ${
                    isSelected ? 'bg-accent-primary/10 text-accent-primary font-semibold' : 'hover:bg-surface-raised text-foreground-secondary'
                  }`}
                >
                  <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${isSelected ? 'text-accent-primary' : 'text-foreground-muted'}`} />
                  <div>
                    <div className="font-medium text-foreground">{agent.name}</div>
                    <div className="text-xs text-foreground-muted font-normal">{agent.desc}</div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
