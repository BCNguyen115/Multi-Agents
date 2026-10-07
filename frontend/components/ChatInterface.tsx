'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { UploadCloud, StopCircle, FileSpreadsheet, FileText, Globe, AlertCircle, X, BarChart3 } from 'lucide-react';
import { ChatMessage as ChatMessageType, CSVMetadata, PEVTraceState } from '../lib/types';
import { ChatMessage } from './ChatMessage';
import { processCSVWithDuckDB } from '../lib/duckdb';
import { DOCUMENT_MAX_MB, isDocumentFile, isTabularFile, splitCategoryHint, TABULAR_MAX_MB } from '../lib/fileTypes';
import { isUnauthorized } from '../lib/authClient';
import { getLang, t, useLang, type MessageKey } from '../lib/i18n';
import { fetchSSEStream } from '../lib/sse';
import { ChatInput } from './ChatInput';
import { toast } from '../lib/toast';
import { applyExecuting, applyFinal, applyPevStep, applyPlan, applyVerifying, createInitialPevTraceState } from '../lib/pevTrace';
import { apiFetch } from '../lib/apiFetch';

/** One-click prompts of the empty chat. `tone` is the hover color of the icon: the agent's state color. */
const STARTERS: { id: 'Data Agent' | 'RAG Agent' | 'Search Agent'; Icon: typeof BarChart3; tone: string; labelKey: MessageKey; tag: string }[] = [
  { id: 'Data Agent', Icon: BarChart3, tone: 'group-hover:bg-accent-primary/10 group-hover:text-accent-primary', labelKey: 'chat.starterDataTitle', tag: 'Data' },
  { id: 'RAG Agent', Icon: FileText, tone: 'group-hover:bg-accent-planner/10 group-hover:text-accent-planner', labelKey: 'chat.starterRagTitle', tag: 'RAG' },
  { id: 'Search Agent', Icon: Globe, tone: 'group-hover:bg-accent-executor/10 group-hover:text-accent-executor', labelKey: 'chat.starterSearchTitle', tag: 'Search' },
];

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
  const [lang] = useLang();
  // Which conversation has a request in flight: a stream started in A must not look "busy" when the user opens B
  const [sendingSession, setSendingSession] = useState<string | null>(null);
  const isSending = sendingSession === sessionId;
  const [attachedFile, setAttachedFile] = useState<File | null>(null);
  const [activeCSV, setActiveCSV] = useState<{ file: File; metadata: CSVMetadata; tableName: string } | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [heroAlert, setHeroAlert] = useState<string | null>(null);
  const controllers = useRef(new Map<string, AbortController>()); // one stream per conversation, each can be stopped

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const isInitialState = messages.length === 0;

  // Leaving the page ends the streams that are still open (their callbacks would keep updating state for nobody)
  useEffect(() => {
    const open = controllers.current;
    return () => open.forEach((controller) => controller.abort());
  }, []);

  // The question each reply answers: the last user message at or before it, computed in one pass
  const userQueries = useMemo(() => {
    let last: string | undefined;
    return messages.map((m) => (m.role === 'user' ? (last = m.content) : last));
  }, [messages]);

  // Auto-scroll
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

  // Shared file processing
  const processFileSelection = async (file: File | null) => {
    if (!file) {
      setAttachedFile(null);
      setActiveCSV(null);
      return;
    }

    const name = file.name.toLowerCase();
    const isExcelOrCSV = isTabularFile(name);
    const isDoc = isDocumentFile(name);

    if (!isExcelOrCSV && !isDoc) {
      toast.error(t(getLang(), 'chat.unsupportedFile'), {
        title: t(getLang(), 'chat.unsupportedFileTitle'),
      });
      return;
    }

    const MAX_SIZE_MB = isExcelOrCSV ? TABULAR_MAX_MB : DOCUMENT_MAX_MB;
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      toast.error(t(getLang(), 'chat.sizeLimit', { max: MAX_SIZE_MB }), {
        title: t(getLang(), 'chat.sizeLimitTitle'),
      });
      return;
    }

    setAttachedFile(file);

    if (isExcelOrCSV && !currentAgentMode.includes('Data Agent')) {
      onSelectAgentMode('Data Agent');
    } else if (isDoc && !currentAgentMode.includes('RAG Agent')) {
      onSelectAgentMode('RAG Agent');
    }

    if (name.endsWith('.csv')) {
      try {
        const { metadata, tableName } = await processCSVWithDuckDB(file);
        setActiveCSV({ file, metadata, tableName });
        const count = metadata.totalRows || metadata.rowCount || 0;
        toast.success(t(getLang(), 'chat.csvLoaded', { count: count.toLocaleString() }), {
          title: 'DuckDB Engine',
        });
      } catch (err: unknown) {
        console.error('DuckDB CSV load failed:', err);
        toast.error(t(getLang(), 'chat.csvLoadFailed'), { title: t(getLang(), 'chat.csvLoadFailedTitle') });
      }
    }
  };

  // Drag & Drop
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(true);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!dragActive) setDragActive(true);
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

  const getTargetAgentId = (mode: string): string | null => {
    if (!mode) return null;
    const m = mode.trim().toLowerCase();
    if (m === 'all agents' || m === 'all_agents' || m === 'auto') return null;
    if (m.includes('rag')) return 'rag_agent';
    if (m.includes('search')) return 'search_agent';
    if (m.includes('data')) return 'data_agent';
    if (m.includes('db') || m.includes('database') || m.includes('sql')) return 'db_agent';
    if (m.includes('integration') || m.includes('api')) return 'integration_agent';
    return null;
  };

  const runStarter = (agent: 'Data Agent' | 'RAG Agent' | 'Search Agent', labelKey: MessageKey) => {
    onSelectAgentMode(agent);
    if (agent === 'Data Agent') {
      if (attachedFile || activeCSV) void handleSendMessageFromInput(t(getLang(), labelKey), attachedFile || activeCSV?.file || null, agent);
      else setHeroAlert(t(getLang(), 'chat.attachCsvAbove'));
      return;
    }
    void handleSendMessageFromInput(t(getLang(), labelKey), null, agent);
  };

  /** Marks the last reply as failed (the analyze and the stream paths share this). */
  const markFailed = (effectiveMode: string, contentKey: MessageKey, descriptionKey: MessageKey, error: string) =>
    onUpdateLastMessage((prev) => {
      const prevState = prev.pevTraceState || createInitialPevTraceState(effectiveMode);
      return {
        ...prev,
        content: t(getLang(), contentKey, { error }),
        pevTraceState: {
          ...prevState,
          currentStep: 'completed',
          verifier: { ...prevState.verifier, status: 'failed', description: t(getLang(), descriptionKey, { error }) },
        },
        status: 'error',
      };
    });

  /** Adds a PDF/DOCX to the knowledge base. Resolves `true` when it was stored and the user also asked a question. */
  const uploadToKnowledgeBase = async (file: File, categoryHint: string | null, hasQuestion: boolean, effectiveMode: string): Promise<boolean> => {
    onUpdateLastMessage((prev) => ({
      ...prev,
      content: t(getLang(), 'upload.processing', { name: file.name }),
      pevEvents: undefined,
      pevTraceState: undefined,
      status: 'complete',
    }));
    let uploaded = false;
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('session_id', sessionId);
      if (categoryHint) formData.append('category', categoryHint);
      const res = await apiFetch('/api/knowledge/upload', { method: 'POST', body: formData });
      const data = await res.json().catch(() => ({}));
      if (isUnauthorized(res)) throw new Error(t(getLang(), 'session.expired'));
      if (!res.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : data.error || `HTTP error ${res.status}`);
      }
      uploaded = true;
      onUpdateLastMessage((prev) => ({ ...prev, content: data.message || t(getLang(), 'chat.kbUpdated'), status: 'complete' }));
      if (data.status !== 'unchanged') {
        toast.success(t(getLang(), 'upload.saved', { chunks: data.chunks, category: data.category }), { title: 'Knowledge base' });
      }
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      onUpdateLastMessage((prev) => ({ ...prev, content: t(getLang(), 'upload.failed', { error: errorMessage }), status: 'error' }));
    }
    if (!uploaded || !hasQuestion) return false;
    // the user also asked something: answer it from the (now updated) knowledge base in a new reply
    onSendMessage({
      id: `assistant-${Date.now()}-answer`,
      role: 'assistant',
      content: '',
      agentMode: effectiveMode,
      pevEvents: {},
      pevTraceState: createInitialPevTraceState(effectiveMode),
      status: 'loading',
    });
    return true;
  };

  /** CSV -> dashboard through /api/analyze. */
  const analyzeCsv = async (queryContent: string, actualFile: File | undefined, effectiveMode: string) => {
    try {
      const formData = new FormData();
      formData.append('query', queryContent);
      formData.append('session_id', sessionId);
      if (actualFile) formData.append('file', actualFile);

      const res = await apiFetch('/api/analyze', { method: 'POST', body: formData });
      const data = await res.json().catch(() => ({}));
      if (isUnauthorized(res)) throw new Error(t(getLang(), 'session.expired'));
      if (!res.ok) {
        // The backend explains 4xx errors (unreadable file, too large, blocked prompt) in `detail`
        throw new Error(typeof data.detail === 'string' ? data.detail : data.error || `HTTP error ${res.status}`);
      }
      const dashboardSpec = data.dashboard_spec ? { ...data.dashboard_spec, sessionId } : undefined;

      const traceFromAnalyze: PEVTraceState = {
        currentStep: 'completed',
        planner: {
          status: 'completed',
          title: 'Planner Node',
          targetAgent: 'data_agent',
          plan: t(getLang(), 'chat.analyzePlan'),
          description: t(getLang(), 'chat.analyzePlanDone'),
        },
        executor: {
          status: 'completed',
          title: 'Executor Node',
          agentName: 'data_agent',
          subTasks: [t(getLang(), 'chat.analyzeSubTask')],
          outputSummary: t(getLang(), 'chat.analyzeOutput'),
        },
        verifier: {
          status: 'completed',
          title: 'Verifier Node',
          isVerified: true,
          auditPassed: true,
          feedback: t(getLang(), 'chat.analyzeFeedback'),
        },
      };

      onUpdateLastMessage((prev) => ({
        ...prev,
        content: data.explanation || t(getLang(), 'chat.analyzed'),
        generatedCode: data.generated_code || '',
        dashboardSpec,
        metadata: data.metadata || undefined,
        pevTrace: data.pev_trace || undefined,
        pevTraceState: traceFromAnalyze,
        status: 'complete',
      }));
    } catch (err: unknown) {
      markFailed(effectiveMode, 'chat.analyzeError', 'chat.errorDescription', err instanceof Error ? err.message : String(err));
    }
  };

  /** Chat turn over SSE. The answer preview arrives token by token: it is applied at most once per animation frame. */
  const streamChat = async (queryContent: string, modeKey: string | null, targetAgentId: string | null, effectiveMode: string) => {
    const origin = sessionId;
    const controller = new AbortController();
    controllers.current.set(origin, controller);

    let pending = '';
    let frame: number | null = null;
    const dropFrame = () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
    };
    const flush = () => {
      dropFrame();
      if (!pending) return;
      const text = pending;
      pending = '';
      onUpdateLastMessage((prev) => ({ ...prev, content: `${prev.content}${text}`, isPreview: true }));
    };
    controller.signal.addEventListener('abort', flush); // what arrived before "Stop" is kept

    try {
      await fetchSSEStream(
        queryContent,
        origin,
        modeKey,
        {
          onPevStep: (stepData) => {
            onUpdateLastMessage((prev) => ({
              ...prev,
              pevStep: stepData,
              pevTraceState: applyPevStep(prev.pevTraceState || createInitialPevTraceState(effectiveMode), stepData),
            }));
          },
          onPlan: (planData) => {
            onUpdateLastMessage((prev) => ({
              ...prev,
              pevEvents: { ...prev.pevEvents, plan: planData },
              pevTraceState: applyPlan(prev.pevTraceState || createInitialPevTraceState(effectiveMode), planData),
            }));
          },
          onExecuting: (execData) => {
            onUpdateLastMessage((prev) => ({
              ...prev,
              pevEvents: { ...prev.pevEvents, executing: execData as any },
              pevTraceState: applyExecuting(prev.pevTraceState || createInitialPevTraceState(effectiveMode), execData),
            }));
          },
          onVerifying: (verifyingData) => {
            onUpdateLastMessage((prev) => ({
              ...prev,
              pevEvents: { ...prev.pevEvents, verifying: verifyingData },
              pevTraceState: applyVerifying(prev.pevTraceState || createInitialPevTraceState(effectiveMode), verifyingData),
            }));
          },
          onHumanApprovalRequired: (approvalData) => {
            onUpdateLastMessage((prev) => ({ ...prev, approvalRequest: approvalData }));
          },
          onAnswerDelta: (text) => {
            pending += text;
            if (frame === null) frame = requestAnimationFrame(flush);
          },
          onAnswerReset: () => {
            dropFrame();
            pending = '';
            onUpdateLastMessage((prev) => ({ ...prev, content: '', isPreview: false }));
          },
          onFinalResponse: (finalData) => {
            dropFrame();
            pending = ''; // the verified answer replaces whatever preview was still waiting
            onUpdateLastMessage((prev) => ({
              ...prev,
              content: finalData.response,
              pevEvents: { ...prev.pevEvents, final_response: finalData },
              pevStep: { step: 'completed', status: 'verified' },
              pevTrace: finalData.pev_trace || prev.pevTrace,
              pevTraceState: applyFinal(prev.pevTraceState || createInitialPevTraceState(effectiveMode), finalData),
              status: 'complete',
              isPreview: false,
            }));
          },
          onError: (err) => {
            dropFrame();
            pending = '';
            markFailed(effectiveMode, 'chat.streamError', 'chat.failedDescription', String(err));
          },
        },
        controller.signal,
        targetAgentId
      );
    } finally {
      flush();
      if (controllers.current.get(origin) === controller) controllers.current.delete(origin);
    }
  };

  const handleSendMessageFromInput = async (
    queryText: string,
    file: File | null,
    overrideMode?: string
  ) => {
    // `/docs` lists the knowledge base documents (with delete buttons) instead of asking an agent
    if (!file && !attachedFile && queryText.trim().toLowerCase() === t(getLang(), 'docs.command')) {
      const stamp = Date.now();
      onSendMessage({ id: `user-${stamp}`, role: 'user', content: t(getLang(), 'docs.userMessage') });
      onSendMessage({ id: `assistant-${stamp}`, role: 'assistant', content: '', kind: 'knowledge-docs', status: 'complete' });
      return;
    }

    const effectiveMode = overrideMode || currentAgentMode;
    const targetAgentId = getTargetAgentId(effectiveMode);

    const fileToUse = file || attachedFile;
    let csvToSend = activeCSV;

    if (fileToUse && (!activeCSV || activeCSV.file !== fileToUse)) {
      if (fileToUse.name.toLowerCase().endsWith('.csv')) {
        try {
          const { metadata, tableName } = await processCSVWithDuckDB(fileToUse);
          csvToSend = { file: fileToUse, metadata, tableName };
          setActiveCSV(csvToSend);
        } catch (err: unknown) {
          console.error('DuckDB CSV load failed:', err);
        }
      }
    }

    if (targetAgentId === 'data_agent' && !csvToSend && !fileToUse && messages.length === 0) {
      setHeroAlert(t(getLang(), 'chat.attachCsvFirst'));
      return;
    }
    setHeroAlert(null);

    // A PDF/DOCX attached to the chat is added to the RAG knowledge base; any text typed with it is a question to ask afterwards
    const isKnowledgeUpload = Boolean(fileToUse && isDocumentFile(fileToUse.name));
    const { category: categoryHint, rest: questionText } = isKnowledgeUpload
      ? splitCategoryHint(queryText)
      : { category: null, rest: queryText.trim() };
    const queryContent = questionText || (isKnowledgeUpload
      ? t(getLang(), 'chat.addDocument', { name: fileToUse?.name ?? '' }) + (categoryHint ? t(getLang(), 'chat.addDocumentCategory', { category: categoryHint }) : '')
      : t(getLang(), 'chat.buildDashboard', { name: fileToUse?.name || 'dataset' }));

    onSendMessage({
      id: `user-${Date.now()}`,
      role: 'user',
      content: isKnowledgeUpload && questionText ? `${questionText}\n\n${t(getLang(), 'chat.attachedNote', { name: fileToUse?.name ?? '' })}` : queryContent,
      agentMode: effectiveMode,
    });
    onSendMessage({
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content: '',
      agentMode: effectiveMode,
      pevEvents: {},
      pevTraceState: createInitialPevTraceState(effectiveMode),
      status: 'loading',
    });
    setAttachedFile(null);

    const origin = sessionId;
    setSendingSession(origin);

    // CRITICAL: Strictly isolate Data Agent routing.
    // If user explicitly selected RAG Agent, Search Agent, DB Agent, etc.,
    // NEVER route to /api/analyze even if an old activeCSV exists in state!
    const isExplicitNonData = targetAgentId !== null && targetAgentId !== 'data_agent';
    const isExplicitData = targetAgentId === 'data_agent';
    const isNewCsvUpload = Boolean(fileToUse && isTabularFile(fileToUse.name));
    const shouldAnalyze = !isKnowledgeUpload && !isExplicitNonData && (isExplicitData ? Boolean(fileToUse || csvToSend || activeCSV) : isNewCsvUpload);

    try {
      if (isKnowledgeUpload && fileToUse) {
        const goOn = await uploadToKnowledgeBase(fileToUse, categoryHint, Boolean(questionText), effectiveMode);
        if (!goOn) return;
      }
      if (shouldAnalyze) {
        await analyzeCsv(queryContent, csvToSend ? csvToSend.file : (fileToUse || activeCSV?.file), effectiveMode);
      } else {
        await streamChat(queryContent, isKnowledgeUpload ? 'rag_agent' : targetAgentId, targetAgentId, effectiveMode);
      }
    } finally {
      // whatever happened (final answer, error, a stream that just ended), this conversation is no longer busy
      setSendingSession((current) => (current === origin ? null : current));
    }
  };

  // The same function for every message: ChatMessage is memoised and must not see a new callback on each render
  const generateDashboardRef = useRef<((prompt?: string) => void) | undefined>(undefined);
  generateDashboardRef.current = (customPrompt) => {
    void handleSendMessageFromInput(customPrompt || t(lang, 'chat.dashboardPrompt'), activeCSV?.file || attachedFile);
  };
  const generateDashboard = useCallback((customPrompt?: string) => generateDashboardRef.current?.(customPrompt), []);

  const stopSending = () => {
    controllers.current.get(sessionId)?.abort();
    controllers.current.delete(sessionId);
    setSendingSession((current) => (current === sessionId ? null : current));
    onUpdateLastMessage((prev) => ({
      ...prev,
      content: prev.content || t(getLang(), 'chat.stopped'),
      status: 'complete' as const,
    }));
  };

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      className="flex-1 flex flex-col h-full min-h-0 min-w-0 relative bg-background overflow-hidden transition-colors duration-200"
    >
      {/* Drag Overlay */}
      {dragActive && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-accent-primary/5 backdrop-blur-md border-2 border-dashed border-accent-primary rounded-2xl transition-all duration-200 pointer-events-none">
          <div className="p-3 bg-accent-primary/10 text-accent-primary rounded-full mb-2 animate-pulse-subtle">
            <UploadCloud className="w-8 h-8" />
          </div>
          <p className="text-base font-semibold text-foreground">
            {t(lang, 'chat.dropTitle')}
          </p>
          <p className="text-xs text-foreground-muted mt-1">
            {t(lang, 'chat.dropHint', { formats: '.csv, .xlsx, .pdf, .docx, .pptx, .txt, .md', max: Math.max(TABULAR_MAX_MB, DOCUMENT_MAX_MB) })}
          </p>
        </div>
      )}

      {isInitialState ? (
        /* ── HERO CENTERED LAYOUT (New Chat) ── */
        <div className="relative isolate flex-1 flex flex-col items-center justify-center w-full max-w-3xl mx-auto px-4 transition-all duration-300 ease-in-out">
          {/* Ambient bloom: a soft light behind the prompt, fading to nothing at the edges (transparent in the light theme) */}
          <div
            aria-hidden="true"
            className="absolute inset-0 -z-10 pointer-events-none"
            style={{ background: 'radial-gradient(ellipse 65% 50% at 50% 48%, var(--color-bloom, transparent) 0%, transparent 72%)' }}
          />
          <h1 className="text-3xl sm:text-4xl font-normal tracking-tight text-foreground text-center leading-tight mb-8 animate-fade-in">
            {t(lang, 'chat.heroTitle')}
          </h1>

          {/* Non-blocking Hero Alert */}
          {heroAlert && (
            <div className="w-full mb-4 p-3.5 bg-accent-error/10 border border-accent-error/20 rounded-xl text-accent-error text-xs flex items-center justify-between animate-fade-in shadow-xs">
              <div className="flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{heroAlert}</span>
              </div>
              <button
                type="button"
                onClick={() => setHeroAlert(null)}
                className="hover:opacity-80 p-0.5 rounded cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-error/50"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

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

          {/* Starter prompts: one quiet row each, no boxes */}
          <ul className="w-full max-w-xl mt-8 space-y-1 animate-fade-in">
            {STARTERS.map(({ id, Icon, tone, labelKey, tag }) => (
              <li key={id}>
                <button
                  type="button"
                  onClick={() => runStarter(id, labelKey)}
                  className="group w-full flex items-center gap-3.5 px-4 py-2.5 rounded-full border border-transparent hover:bg-surface-raised hover:border-border transition-colors duration-150 text-left cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40"
                >
                  <span className={`p-1.5 rounded-full bg-surface-raised text-foreground-muted transition-colors ${tone}`}>
                    <Icon className="w-4 h-4" aria-hidden="true" />
                  </span>
                  <span className="flex-1 truncate text-sm text-foreground-secondary group-hover:text-foreground transition-colors">{t(lang, labelKey)}</span>
                  <span className="text-xs font-mono text-foreground-muted px-2 py-0.5 rounded-full bg-surface-raised border border-border">{tag}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        /* ── ACTIVE CHAT WINDOW ── */
        <div className="flex-1 flex flex-col justify-between h-full overflow-hidden transition-all duration-300 ease-in-out">
          <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-4 py-6 scroll-smooth">
            <div className="max-w-5xl mx-auto space-y-6 pb-6">
              {messages.map((msg, index) => (
                <ChatMessage
                  key={msg.id}
                  message={msg}
                  userQuery={userQueries[index]}
                  isSending={isSending}
                  isLastMessage={index === messages.length - 1}
                  activeCSV={activeCSV}
                  onGenerateDashboard={generateDashboard}
                />
              ))}
              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Sticky bottom input */}
          <div className="w-full max-w-3xl mx-auto px-4 pt-2 pb-4 shrink-0 bg-gradient-to-t from-background via-background/90 to-transparent z-20">
            {isSending && (
              <div className="flex justify-center mb-2">
                <button
                  type="button"
                  onClick={stopSending}
                  className="flex items-center gap-2 px-4 py-2 bg-surface-raised hover:bg-surface-overlay border border-border rounded-full text-sm font-medium text-foreground-secondary hover:text-foreground transition-all duration-200 cursor-pointer group"
                >
                  <StopCircle className="w-4 h-4 text-accent-error group-hover:scale-110 transition-transform" />
                  <span>{t(lang, 'chat.stop')}</span>
                </button>
              </div>
            )}
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
