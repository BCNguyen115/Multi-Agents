'use client';

import React, { useState, useRef, useEffect } from 'react';
import { UploadCloud } from 'lucide-react';
import { ChatMessage as ChatMessageType, CSVMetadata } from '../lib/types';
import { ChatMessage } from './ChatMessage';
import { processCSVWithDuckDB } from '../lib/duckdb';
import { fetchSSEStream } from '../lib/sse';
import { ChatInput } from './ChatInput';

interface ChatInterfaceProps {
  currentAgentMode: string;
  onSelectAgentMode: (mode: string) => void;
  sessionId: string;
  messages: ChatMessageType[];
  onSendMessage: (msg: ChatMessageType) => void;
  onUpdateLastMessage: (updater: (prev: ChatMessageType) => ChatMessageType) => void;
}

export const ChatInterface: React.FC<ChatInterfaceProps> = ({
  currentAgentMode,
  onSelectAgentMode,
  sessionId,
  messages,
  onSendMessage,
  onUpdateLastMessage,
}) => {
  const [isSending, setIsSending] = useState(false);
  const [attachedFile, setAttachedFile] = useState<File | null>(null);
  const [activeCSV, setActiveCSV] = useState<{ file: File; metadata: CSVMetadata; tableName: string } | null>(null);
  const [dragActive, setDragActive] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const isInitialState = messages.length === 0;

  // Auto-scroll Throttling với requestAnimationFrame & auto/smooth behavior
  useEffect(() => {
    let animationFrameId: number;
    if (messagesEndRef.current) {
      animationFrameId = requestAnimationFrame(() => {
        if (isSending) {
          messagesEndRef.current?.scrollIntoView({ behavior: 'auto', block: 'end' });
        } else {
          messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
      });
    }
    return () => cancelAnimationFrame(animationFrameId);
  }, [messages, isSending]);

  // HÀM DÙNG CHUNG (SINGLE SOURCE OF TRUTH) CHO CẢ NÚT + VÀ DRAG & DROP
  const processFileSelection = async (file: File | null) => {
    if (!file) {
      setAttachedFile(null);
      setActiveCSV(null);
      return;
    }

    const name = file.name.toLowerCase();
    const isExcelOrCSV = name.endsWith('.csv') || name.endsWith('.xlsx') || name.endsWith('.xls');
    const isDoc = name.endsWith('.pdf') || name.endsWith('.docx') || name.endsWith('.doc') || name.endsWith('.txt');

    if (!isExcelOrCSV && !isDoc) {
      alert('⚠️ Định dạng file không được hỗ trợ. Vui lòng chọn file CSV, Excel, PDF hoặc Word (.csv, .xlsx, .pdf, .docx).');
      return;
    }

    const MAX_SIZE_MB = 50;
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      alert(`⚠️ Dung lượng file vượt quá giới hạn ${MAX_SIZE_MB}MB.`);
      return;
    }

    setAttachedFile(file);

    // Auto-switch Agent mode tương ứng loại file
    if (isExcelOrCSV && !currentAgentMode.includes('Data Agent')) {
      onSelectAgentMode('📊 Data Agent');
    } else if (isDoc && !currentAgentMode.includes('RAG Agent')) {
      onSelectAgentMode('RAG Agent');
    }

    // Nếu là file CSV thì nạp DuckDB client-side
    if (name.endsWith('.csv')) {
      try {
        const { metadata, tableName } = await processCSVWithDuckDB(file);
        setActiveCSV({ file, metadata, tableName });
      } catch (err: any) {
        console.error('Lỗi khi nạp CSV DuckDB:', err);
      }
    }
  };

  // Drag & Drop Handlers Chuẩn Kỹ Thuật
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(true);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!dragActive) {
      setDragActive(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setDragActive(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      processFileSelection(e.dataTransfer.files[0]);
    }
  };

  const handleSendMessageFromInput = async (queryText: string, file: File | null) => {
    let fileToUse = file || attachedFile;
    let csvToSend = activeCSV;

    if (fileToUse && (!activeCSV || activeCSV.file !== fileToUse)) {
      if (fileToUse.name.toLowerCase().endsWith('.csv')) {
        try {
          const { metadata, tableName } = await processCSVWithDuckDB(fileToUse);
          csvToSend = { file: fileToUse, metadata, tableName };
          setActiveCSV(csvToSend);
        } catch (err: any) {
          console.error('Lỗi khi nạp CSV DuckDB:', err);
        }
      }
    }

    // Only alert for missing file if starting a fresh session with no prior messages
    if (currentAgentMode.includes('Data Agent') && !csvToSend && !fileToUse && messages.length === 0) {
      alert('⚠️ Vui lòng đính kèm file CSV (bằng nút + hoặc kéo thả) trước khi bắt đầu chat phân tích dữ liệu!');
      return;
    }

    const queryContent = queryText.trim() || `Phân tích tổng quan dữ liệu tệp CSV [${fileToUse?.name || 'dataset.csv'}]`;

    const userMessage: ChatMessageType = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: queryContent,
      agentMode: currentAgentMode,
    };

    onSendMessage(userMessage);

    const assistantId = `assistant-${Date.now()}`;
    const initialAssistantMsg: ChatMessageType = {
      id: assistantId,
      role: 'assistant',
      content: '',
      agentMode: currentAgentMode,
      pevEvents: {},
      status: 'loading',
    };

    onSendMessage(initialAssistantMsg);
    setAttachedFile(null);
    setActiveCSV(null);
    setIsSending(true);

    if (currentAgentMode.includes('Data Agent') || fileToUse) {
      // Data Agent Mode: Send CSV analysis payload to /api/analyze (supports Redis session context fallback)
      try {
        const formData = new FormData();
        formData.append('query', queryContent);
        formData.append('session_id', sessionId);
        const actualFile = csvToSend ? csvToSend.file : fileToUse;
        if (actualFile) {
          formData.append('file', actualFile);
        }

        const res = await fetch('/api/analyze', {
          method: 'POST',
          body: formData,
        });

        if (!res.ok) throw new Error(`HTTP error ${res.status}`);

        const data = await res.json();
        onUpdateLastMessage((prev) => ({
          ...prev,
          content: data.explanation || 'Đã phân tích xong dữ liệu.',
          generatedCode: data.generated_code || '',
          dashboardSpec: data.dashboard_spec || undefined,
          metadata: data.metadata || undefined,
          pevTrace: data.pev_trace || undefined,
          status: 'complete',
        }));
      } catch (err: any) {
        onUpdateLastMessage((prev) => ({
          ...prev,
          content: `❌ Lỗi khi phân tích dữ liệu CSV: ${err.message || err}`,
          status: 'error',
        }));
      } finally {
        setIsSending(false);
      }
    } else {
      // RAG Agent / Search Agent: Real-time SSE PEV Loop Stream
      const modeKey = currentAgentMode.includes('Search') ? 'search_agent' : null;

      await fetchSSEStream(queryContent, sessionId, modeKey, {
        onPevStep: (stepData) => {
          onUpdateLastMessage((prev) => ({
            ...prev,
            pevStep: stepData,
          }));
        },
        onPlan: (planData) => {
          onUpdateLastMessage((prev) => ({
            ...prev,
            pevEvents: {
              ...prev.pevEvents,
              plan: planData,
            },
          }));
        },
        onExecuting: (execData) => {
          onUpdateLastMessage((prev) => ({
            ...prev,
            pevEvents: {
              ...prev.pevEvents,
              executing: execData,
            },
          }));
        },
        onVerifying: (verifyingData) => {
          onUpdateLastMessage((prev) => ({
            ...prev,
            pevEvents: {
              ...prev.pevEvents,
              verifying: verifyingData,
            },
          }));
        },
        onFinalResponse: (finalData) => {
          onUpdateLastMessage((prev) => ({
            ...prev,
            content: finalData.response,
            pevEvents: {
              ...prev.pevEvents,
              final_response: finalData,
            },
            pevStep: {
              step: 'completed',
              status: 'verified',
            },
            status: 'complete',
          }));
          setIsSending(false);
        },
        onError: (err) => {
          onUpdateLastMessage((prev) => ({
            ...prev,
            content: `❌ Lỗi thực thi stream: ${err}`,
            status: 'error',
          }));
          setIsSending(false);
        },
      });
    }
  };

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className="flex-1 flex flex-col h-full min-h-0 min-w-0 relative bg-white dark:bg-slate-900 overflow-hidden transition-colors duration-300"
    >
      {/* Drag & Drop Visual Cue Overlay */}
      {dragActive && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-blue-50/85 dark:bg-slate-900/85 backdrop-blur-md border-2 border-dashed border-blue-500 rounded-2xl transition-all duration-200 pointer-events-none">
          <div className="p-3 bg-blue-100 dark:bg-blue-900/60 text-blue-600 dark:text-blue-400 rounded-full mb-2 animate-bounce">
            <UploadCloud className="w-8 h-8" />
          </div>
          <p className="text-base font-semibold text-slate-800 dark:text-slate-100">
            Kéo & thả file CSV / Excel / Document vào đây để nạp tự động
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Hỗ trợ các định dạng .csv, .xlsx, .pdf, .docx (Tối đa 50MB)
          </p>
        </div>
      )}

      {isInitialState ? (
        /* ---------------- 1. TRẠNG THÁI NEW CHAT (HERO CENTERED LAYOUT) ---------------- */
        <div className="flex-1 flex flex-col items-center justify-center w-full max-w-3xl mx-auto px-4 -mt-12 transition-all duration-300 ease-in-out">
          {/* Tiêu đề chào mừng Gemini Style */}
          <h1 className="text-3xl sm:text-4xl md:text-5xl font-medium tracking-tight text-center bg-gradient-to-r from-[#005697] via-slate-800 to-[#F37021] dark:from-blue-400 dark:via-slate-100 dark:to-orange-400 bg-clip-text text-transparent leading-tight mb-8 animate-in fade-in duration-300">
            Tôi có thể giúp gì cho bạn hôm nay?
          </h1>

          {/* Thanh Chat Input nằm ngay bên dưới tiêu đề, căn giữa tuyệt đối */}
          <div className="w-full">
            <ChatInput
              selectedAgent={currentAgentMode}
              onSelectAgent={onSelectAgentMode}
              onSendMessage={handleSendMessageFromInput}
              isSending={isSending}
              attachedFile={attachedFile}
              onFileSelect={processFileSelection}
            />
          </div>
        </div>
      ) : (
        /* ---------------- 2. TRẠNG THÁI ĐÃ CHAT (ACTIVE CHAT WINDOW) ---------------- */
        <div className="flex-1 flex flex-col justify-between h-full overflow-hidden transition-all duration-300 ease-in-out">
          {/* Khung chứa các tin nhắn chat */}
          <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-4 py-6 scroll-smooth">
            <div className="max-w-5xl mx-auto space-y-6 pb-6">
              {messages.map((msg, index) => (
                <ChatMessage
                  key={msg.id}
                  message={msg}
                  isSending={isSending}
                  isLastMessage={index === messages.length - 1}
                  activeCSV={activeCSV}
                  onGenerateDashboard={(customPrompt) =>
                    handleSendMessageFromInput(
                      customPrompt || 'Dựng dashboard trực quan từ dữ liệu này',
                      activeCSV?.file || attachedFile
                    )
                  }
                />
              ))}
              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Thanh Chat Input dính ở đáy */}
          <div className="w-full max-w-3xl mx-auto px-4 pt-2 pb-4 shrink-0 bg-gradient-to-t from-white via-white/90 to-transparent dark:from-slate-900 dark:via-slate-900/90 dark:to-transparent z-20">
            <ChatInput
              selectedAgent={currentAgentMode}
              onSelectAgent={onSelectAgentMode}
              onSendMessage={handleSendMessageFromInput}
              isSending={isSending}
              attachedFile={attachedFile}
              onFileSelect={processFileSelection}
            />
          </div>
        </div>
      )}
    </div>
  );
};
