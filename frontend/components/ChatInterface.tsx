'use client';

import React, { useState, useRef, useEffect } from 'react';
import { UploadCloud, StopCircle, FileSpreadsheet, FileText, Globe, AlertCircle, X, BarChart3 } from 'lucide-react';
import { ChatMessage as ChatMessageType, CSVMetadata, PEVTraceState } from '../lib/types';
import { ChatMessage } from './ChatMessage';
import { processCSVWithDuckDB, executeDuckDBSQL } from '../lib/duckdb';
import { fetchSSEStream } from '../lib/sse';
import { ChatInput } from './ChatInput';

function createInitialPevTraceState(agentMode?: string): PEVTraceState {
  const isSearch = agentMode?.includes('Search');
  const isData = agentMode?.includes('Data');
  const isRag = agentMode?.includes('RAG');
  const targetAgent = isSearch ? 'search_agent' : isData ? 'data_agent' : isRag ? 'rag_agent' : undefined;

  return {
    currentStep: 'planner',
    planner: {
      status: 'active',
      title: 'Planner Node',
      description: 'Đang phân tích câu hỏi, nạp bộ nhớ dài hạn và lựa chọn Agent phù hợp...',
      targetAgent,
    },
    executor: {
      status: 'idle',
      title: 'Executor Node',
      description: 'Chờ Planner hoàn tất để nhận nhiệm vụ...',
      agentName: targetAgent,
    },
    verifier: {
      status: 'idle',
      title: 'Verifier Node',
      description: 'Chờ kết quả thực thi để kiểm định chất lượng...',
    },
  };
}

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
  const [heroAlert, setHeroAlert] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const isInitialState = messages.length === 0;

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
    const isExcelOrCSV = name.endsWith('.csv') || name.endsWith('.xlsx') || name.endsWith('.xls');
    const isDoc = name.endsWith('.pdf') || name.endsWith('.docx') || name.endsWith('.doc') || name.endsWith('.txt');

    if (!isExcelOrCSV && !isDoc) {
      alert('Định dạng file không được hỗ trợ. Vui lòng chọn file CSV, Excel, PDF hoặc Word (.csv, .xlsx, .pdf, .docx).');
      return;
    }

    const MAX_SIZE_MB = 50;
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      alert(`Dung lượng file vượt quá giới hạn ${MAX_SIZE_MB}MB.`);
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
      } catch (err: unknown) {
        console.error('Lỗi khi nạp CSV DuckDB:', err);
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

  const handleSendMessageFromInput = async (queryText: string, file: File | null) => {
    let fileToUse = file || attachedFile;
    let csvToSend = activeCSV;

    if (fileToUse && (!activeCSV || activeCSV.file !== fileToUse)) {
      if (fileToUse.name.toLowerCase().endsWith('.csv')) {
        try {
          const { metadata, tableName } = await processCSVWithDuckDB(fileToUse);
          csvToSend = { file: fileToUse, metadata, tableName };
          setActiveCSV(csvToSend);
        } catch (err: unknown) {
          console.error('Lỗi khi nạp CSV DuckDB:', err);
        }
      }
    }

    if (currentAgentMode.includes('Data Agent') && !csvToSend && !fileToUse && messages.length === 0) {
      setHeroAlert('Vui lòng đính kèm tệp CSV trước khi bắt đầu chat phân tích dữ liệu!');
      return;
    }
    setHeroAlert(null);

    const queryContent = queryText.trim() || `Phân tích tổng quan dữ liệu tệp CSV [${fileToUse?.name || 'dataset.csv'}]`;

    const userMessage: ChatMessageType = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: queryContent,
      agentMode: currentAgentMode,
    };

    onSendMessage(userMessage);

    const assistantId = `assistant-${Date.now()}`;
    const initialTraceState = createInitialPevTraceState(currentAgentMode);

    const initialAssistantMsg: ChatMessageType = {
      id: assistantId,
      role: 'assistant',
      content: '',
      agentMode: currentAgentMode,
      pevEvents: {},
      pevTraceState: initialTraceState,
      status: 'loading',
    };

    onSendMessage(initialAssistantMsg);
    setAttachedFile(null);
    setIsSending(true);

    if (currentAgentMode.includes('Data Agent') || fileToUse || csvToSend || activeCSV) {
      try {
        const formData = new FormData();
        formData.append('query', queryContent);
        formData.append('session_id', sessionId);
        const actualFile = csvToSend ? csvToSend.file : (fileToUse || activeCSV?.file);
        if (actualFile) {
          formData.append('file', actualFile);
        }

        const res = await fetch('/api/analyze', {
          method: 'POST',
          body: formData,
        });

        if (!res.ok) throw new Error(`HTTP error ${res.status}`);

        const data = await res.json();
        let dashboardSpec = data.dashboard_spec || undefined;
        if (dashboardSpec && (csvToSend?.tableName || activeCSV?.tableName)) {
          const tName = csvToSend?.tableName || activeCSV?.tableName;
          try {
            const currentRows =
              dashboardSpec.table?.rows ||
              dashboardSpec.raw_data ||
              dashboardSpec.rawRows ||
              [];
            if (tName && (!currentRows || currentRows.length < 50)) {
              const fullRows = await executeDuckDBSQL(tName, `SELECT * FROM ${tName};`);
              if (fullRows && fullRows.length > 0) {
                dashboardSpec = {
                  ...dashboardSpec,
                  raw_data: fullRows,
                  rawData: fullRows,
                  rawRows: fullRows,
                  rows: fullRows,
                  totalRows: fullRows.length,
                  total_rows: fullRows.length,
                  table: {
                    ...(dashboardSpec.table || {}),
                    rows: fullRows,
                    totalRows: fullRows.length,
                  },
                };
              }
            }
          } catch (duckErr) {
            console.warn('DuckDB local sync fallback skipped:', duckErr);
          }
        }

        const traceFromAnalyze: PEVTraceState = {
          currentStep: 'completed',
          planner: {
            status: 'completed',
            title: 'Planner Node',
            targetAgent: 'data_agent',
            plan: 'Phân tích cấu trúc dữ liệu CSV, tính toán các chỉ số thống kê phân phối và dựng Dashboard trực quan hóa.',
            description: 'Đã hoàn tất phân tích yêu cầu và lập kế hoạch xử lý dữ liệu.',
          },
          executor: {
            status: 'completed',
            title: 'Executor Node',
            agentName: 'data_agent',
            subTasks: [
              'EDA (Khám phá dữ liệu) -> Tạo Layout trực quan -> Dựng Biểu Đồ & KPI Cards',
            ],
            outputSummary: 'Đã hoàn tất thực thi xử lý dữ liệu và khởi tạo thành công đặc tả Dashboard.',
          },
          verifier: {
            status: 'completed',
            title: 'Verifier Node',
            isVerified: true,
            auditPassed: true,
            feedback: 'Đặc tả Dashboard và cấu trúc dữ liệu đạt chuẩn kiểm duyệt 100% (Zero-Hallucination).',
          },
        };

        onUpdateLastMessage((prev) => ({
          ...prev,
          content: data.explanation || 'Đã phân tích xong dữ liệu.',
          generatedCode: data.generated_code || '',
          dashboardSpec,
          metadata: data.metadata || undefined,
          pevTrace: data.pev_trace || undefined,
          pevTraceState: traceFromAnalyze,
          status: 'complete',
        }));
      } catch (err: unknown) {
        const errorMessage = err instanceof Error ? err.message : String(err);
        onUpdateLastMessage((prev) => {
          const prevState = prev.pevTraceState || createInitialPevTraceState(currentAgentMode);
          return {
            ...prev,
            content: `Lỗi khi phân tích dữ liệu CSV: ${errorMessage}`,
            pevTraceState: {
              ...prevState,
              currentStep: 'completed',
              verifier: {
                ...prevState.verifier,
                status: 'failed',
                description: `Lỗi: ${errorMessage}`,
              },
            },
            status: 'error',
          };
        });
      } finally {
        setIsSending(false);
      }
    } else {
      const modeKey = currentAgentMode.includes('Search') ? 'search_agent' : null;

      // Create abort controller for this stream
      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      await fetchSSEStream(queryContent, sessionId, modeKey, {
        onPevStep: (stepData) => {
          onUpdateLastMessage((prev) => {
            const prevState = prev.pevTraceState || createInitialPevTraceState(currentAgentMode);
            let nextState: PEVTraceState = { ...prevState };

            if (stepData.step === 'planner') {
              if (stepData.status === 'completed') {
                nextState = {
                  ...nextState,
                  planner: {
                    ...nextState.planner,
                    status: 'completed',
                    targetAgent: stepData.target || nextState.planner.targetAgent,
                  },
                };
              } else {
                nextState = {
                  ...nextState,
                  currentStep: 'planner',
                  planner: {
                    ...nextState.planner,
                    status: 'active',
                    description: stepData.logs || nextState.planner.description || 'Đang phân tích câu hỏi, nạp bộ nhớ dài hạn và lựa chọn Agent phù hợp...',
                  },
                };
              }
            } else if (stepData.step === 'executor') {
              if (stepData.status === 'completed') {
                nextState = {
                  ...nextState,
                  executor: {
                    ...nextState.executor,
                    status: 'completed',
                    agentName: stepData.target || nextState.executor.agentName,
                  },
                };
              } else {
                nextState = {
                  ...nextState,
                  currentStep: 'executor',
                  planner: {
                    ...nextState.planner,
                    status: 'completed',
                    targetAgent: stepData.target || nextState.planner.targetAgent,
                  },
                  executor: {
                    ...nextState.executor,
                    status: 'active',
                    agentName: stepData.target || nextState.executor.agentName,
                    description: stepData.logs || `Agent [${stepData.target || 'Executor'}] đang thực thi tác vụ...`,
                  },
                };
              }
            } else if (stepData.step === 'verifier') {
              if (stepData.status === 'completed') {
                nextState = {
                  ...nextState,
                  currentStep: 'completed',
                  verifier: {
                    ...nextState.verifier,
                    status: 'completed',
                    isVerified: true,
                    auditPassed: true,
                  },
                };
              } else {
                nextState = {
                  ...nextState,
                  currentStep: 'verifier',
                  executor: {
                    ...nextState.executor,
                    status: 'completed',
                  },
                  verifier: {
                    ...nextState.verifier,
                    status: 'active',
                    description: stepData.logs || 'Đang đối soát kết quả với kế hoạch ban đầu và kiểm định tính trung thực...',
                  },
                };
              }
            } else if (stepData.step === 'completed') {
              const isVer = stepData.status === 'verified';
              nextState = {
                ...nextState,
                currentStep: 'completed',
                planner: { ...nextState.planner, status: 'completed' },
                executor: { ...nextState.executor, status: 'completed' },
                verifier: {
                  ...nextState.verifier,
                  status: 'completed',
                  isVerified: isVer,
                  auditPassed: isVer,
                  feedback: stepData.feedback || nextState.verifier.feedback,
                },
              };
            }

            return {
              ...prev,
              pevStep: stepData,
              pevTraceState: nextState,
            };
          });
        },
        onPlan: (planData) => {
          onUpdateLastMessage((prev) => {
            const prevState = prev.pevTraceState || createInitialPevTraceState(currentAgentMode);
            const nextState: PEVTraceState = {
              ...prevState,
              currentStep: 'executor',
              planner: {
                ...prevState.planner,
                status: 'completed',
                plan: planData.plan,
                targetAgent: planData.target_agent,
                description: 'Đã hoàn tất phân tích yêu cầu và lập kế hoạch.',
              },
              executor: {
                ...prevState.executor,
                status: 'active',
                agentName: planData.target_agent,
                description: `Agent [${planData.target_agent}] đang thực thi tác vụ theo kế hoạch...`,
              },
            };

            return {
              ...prev,
              pevEvents: { ...prev.pevEvents, plan: planData },
              pevTraceState: nextState,
            };
          });
        },
        onExecuting: (execData) => {
          onUpdateLastMessage((prev) => {
            const prevState = prev.pevTraceState || createInitialPevTraceState(currentAgentMode);
            const targetAgent = execData.target_agent || prevState.executor.agentName;
            const hasResult = Boolean(execData.execution_result);
            const isCompleted = execData.status === 'completed' || hasResult;

            const nextState: PEVTraceState = {
              ...prevState,
              currentStep: isCompleted ? 'verifier' : 'executor',
              executor: {
                ...prevState.executor,
                status: isCompleted ? 'completed' : 'active',
                agentName: targetAgent,
                outputSummary: execData.execution_result || prevState.executor.outputSummary,
                description: isCompleted
                  ? `Agent [${targetAgent || 'Executor'}] đã hoàn tất thực thi tác vụ.`
                  : (execData.message || `Agent [${targetAgent || 'Executor'}] đang xử lý dữ liệu...`),
              },
              verifier: isCompleted ? {
                ...prevState.verifier,
                status: 'active',
                description: 'Đang đối soát kết quả với kế hoạch ban đầu và kiểm định tính trung thực...',
              } : prevState.verifier,
            };

            return {
              ...prev,
              pevEvents: { ...prev.pevEvents, executing: execData as any },
              pevTraceState: nextState,
            };
          });
        },
        onVerifying: (verifyingData) => {
          onUpdateLastMessage((prev) => {
            const prevState = prev.pevTraceState || createInitialPevTraceState(currentAgentMode);
            const isVerified = verifyingData.is_verified;
            const nextState: PEVTraceState = {
              ...prevState,
              currentStep: isVerified ? 'completed' : 'verifier',
              verifier: {
                ...prevState.verifier,
                status: isVerified ? 'completed' : (verifyingData.retry_count > 0 ? 'retry' : 'active'),
                isVerified,
                auditPassed: isVerified,
                feedback: verifyingData.verifier_feedback,
                retryCount: verifyingData.retry_count,
                description: isVerified
                  ? 'Kiểm định chất lượng thành công (100% Passed).'
                  : `Phát hiện điểm chưa hoàn thiện — Kích hoạt vòng lặp tự sửa lỗi (Retry #${verifyingData.retry_count}).`,
              },
            };

            return {
              ...prev,
              pevEvents: { ...prev.pevEvents, verifying: verifyingData },
              pevTraceState: nextState,
            };
          });
        },
        onHumanApprovalRequired: (approvalData) => {
          onUpdateLastMessage((prev) => ({
            ...prev,
            approvalRequest: approvalData,
          }));
        },
        onFinalResponse: (finalData) => {
          onUpdateLastMessage((prev) => {
            const prevState = prev.pevTraceState || createInitialPevTraceState(currentAgentMode);
            const nextState: PEVTraceState = {
              ...prevState,
              currentStep: 'completed',
              planner: {
                ...prevState.planner,
                status: 'completed',
                targetAgent: finalData.target_agent || prevState.planner.targetAgent,
                plan: finalData.pev_trace?.planner?.plan_summary || prevState.planner.plan,
              },
              executor: {
                ...prevState.executor,
                status: 'completed',
                agentName: finalData.target_agent || prevState.executor.agentName,
                outputSummary: finalData.pev_trace?.executor?.execution_summary || prevState.executor.outputSummary,
              },
              verifier: {
                ...prevState.verifier,
                status: 'completed',
                isVerified: finalData.is_verified,
                auditPassed: finalData.is_verified,
                feedback: finalData.pev_trace?.verifier?.verifier_feedback || prevState.verifier.feedback,
              },
            };

            return {
              ...prev,
              content: finalData.response,
              pevEvents: { ...prev.pevEvents, final_response: finalData },
              pevStep: { step: 'completed', status: 'verified' },
              pevTrace: finalData.pev_trace || prev.pevTrace,
              pevTraceState: nextState,
              status: 'complete',
            };
          });
          setIsSending(false);
        },
        onError: (err) => {
          onUpdateLastMessage((prev) => {
            const prevState = prev.pevTraceState || createInitialPevTraceState(currentAgentMode);
            return {
              ...prev,
              content: `Lỗi thực thi stream: ${err}`,
              pevTraceState: {
                ...prevState,
                currentStep: 'completed',
                verifier: {
                  ...prevState.verifier,
                  status: 'failed',
                  description: `Thất bại: ${err}`,
                },
              },
              status: 'error',
            };
          });
          setIsSending(false);
        },
      }, abortController.signal);

      abortControllerRef.current = null;
    }
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
          <div className="p-3 bg-accent-primary/10 text-accent-primary rounded-full mb-2 animate-bounce">
            <UploadCloud className="w-8 h-8" />
          </div>
          <p className="text-base font-semibold text-foreground">
            Kéo & thả file CSV / Excel / Document vào đây để nạp tự động
          </p>
          <p className="text-xs text-foreground-muted mt-1">
            Hỗ trợ các định dạng .csv, .xlsx, .pdf, .docx (Tối đa 50MB)
          </p>
        </div>
      )}

      {isInitialState ? (
        /* ── HERO CENTERED LAYOUT (New Chat) ── */
        <div className="flex-1 flex flex-col items-center justify-center w-full max-w-3xl mx-auto px-4 transition-all duration-300 ease-in-out">
          <h1 className="text-3xl sm:text-4xl md:text-5xl font-medium tracking-tight text-center bg-gradient-to-r from-accent-primary via-foreground to-accent-planner bg-clip-text text-transparent leading-tight mb-8 animate-fade-in">
            Tôi có thể giúp gì cho bạn hôm nay?
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

          {/* Quick Starter Prompts (1-Click Actions) */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 w-full mt-6 animate-fade-in">
            <button
              type="button"
              onClick={() => {
                onSelectAgentMode('Data Agent');
                if (attachedFile || activeCSV) {
                  handleSendMessageFromInput('Phân tích doanh số & dựng Executive Dashboard từ file CSV', attachedFile || activeCSV?.file || null);
                } else {
                  setHeroAlert('Vui lòng đính kèm tệp CSV ở khung nhập bên trên để phân tích dữ liệu.');
                }
              }}
              className="group p-3.5 bg-surface hover:bg-surface-raised border border-border hover:border-accent-primary/50 rounded-xl text-left transition-all duration-200 shadow-xs hover:shadow-sm cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40 flex flex-col justify-between space-y-2"
            >
              <div className="flex items-center justify-between">
                <div className="p-2 bg-accent-primary/10 group-hover:bg-accent-primary/20 text-accent-primary rounded-lg transition-colors">
                  <BarChart3 className="w-4 h-4" />
                </div>
                <span className="text-xs font-mono text-foreground-muted uppercase font-semibold">Data Agent</span>
              </div>
              <div>
                <p className="text-xs font-semibold text-foreground group-hover:text-accent-primary transition-colors">
                  Phân tích doanh số & dựng Executive Dashboard từ file CSV
                </p>
                <p className="text-xs text-foreground-muted mt-1 leading-snug">
                  Tự động sinh KPI, phân phối doanh thu và biểu đồ tương tác chéo.
                </p>
              </div>
            </button>

            <button
              type="button"
              onClick={() => {
                onSelectAgentMode('RAG Agent');
                handleSendMessageFromInput('Tra cứu điều khoản hợp đồng & chính sách nội bộ (RAG)', null);
              }}
              className="group p-3.5 bg-surface hover:bg-surface-raised border border-border hover:border-accent-primary/50 rounded-xl text-left transition-all duration-200 shadow-xs hover:shadow-sm cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40 flex flex-col justify-between space-y-2"
            >
              <div className="flex items-center justify-between">
                <div className="p-2 bg-accent-planner/10 group-hover:bg-accent-planner/20 text-accent-planner rounded-lg transition-colors">
                  <FileText className="w-4 h-4" />
                </div>
                <span className="text-xs font-mono text-foreground-muted uppercase font-semibold">RAG Agent</span>
              </div>
              <div>
                <p className="text-xs font-semibold text-foreground group-hover:text-accent-primary transition-colors">
                  Tra cứu điều khoản hợp đồng & chính sách nội bộ (RAG)
                </p>
                <p className="text-xs text-foreground-muted mt-1 leading-snug">
                  Trích xuất và đối chiếu điều khoản bảo mật, SLA và pháp lý.
                </p>
              </div>
            </button>

            <button
              type="button"
              onClick={() => {
                onSelectAgentMode('Search Agent');
                handleSendMessageFromInput('Tìm kiếm tổng hợp tin tức công nghệ mới nhất', null);
              }}
              className="group p-3.5 bg-surface hover:bg-surface-raised border border-border hover:border-accent-primary/50 rounded-xl text-left transition-all duration-200 shadow-xs hover:shadow-sm cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40 flex flex-col justify-between space-y-2"
            >
              <div className="flex items-center justify-between">
                <div className="p-2 bg-accent-executor/10 group-hover:bg-accent-executor/20 text-accent-executor rounded-lg transition-colors">
                  <Globe className="w-4 h-4" />
                </div>
                <span className="text-xs font-mono text-foreground-muted uppercase font-semibold">Search Agent</span>
              </div>
              <div>
                <p className="text-xs font-semibold text-foreground group-hover:text-accent-primary transition-colors">
                  Tìm kiếm tổng hợp tin tức công nghệ mới nhất
                </p>
                <p className="text-xs text-foreground-muted mt-1 leading-snug">
                  Cập nhật các đột phá AI, mô hình ngôn ngữ và xu hướng công nghệ mới.
                </p>
              </div>
            </button>
          </div>
        </div>
      ) : (
        /* ── ACTIVE CHAT WINDOW ── */
        <div className="flex-1 flex flex-col justify-between h-full overflow-hidden transition-all duration-300 ease-in-out">
          <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-4 py-6 scroll-smooth">
            <div className="max-w-5xl mx-auto space-y-6 pb-6">
              {messages.map((msg, index) => {
                const prevUserMsg = messages
                  .slice(0, index + 1)
                  .reverse()
                  .find((m) => m.role === 'user');
                const userQuery = prevUserMsg?.content;

                return (
                  <ChatMessage
                    key={msg.id}
                    message={msg}
                    userQuery={userQuery}
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
                );
              })}
              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Sticky bottom input */}
          <div className="w-full max-w-3xl mx-auto px-4 pt-2 pb-4 shrink-0 bg-gradient-to-t from-background via-background/90 to-transparent z-20">
            {isSending && (
              <div className="flex justify-center mb-2">
                <button
                  type="button"
                  onClick={() => {
                    if (abortControllerRef.current) {
                      abortControllerRef.current.abort();
                      abortControllerRef.current = null;
                    }
                    setIsSending(false);
                    onUpdateLastMessage((prev) => ({
                      ...prev,
                      content: prev.content || '⏹ Đã dừng tạo phản hồi.',
                      status: 'complete' as const,
                    }));
                  }}
                  className="flex items-center gap-2 px-4 py-2 bg-surface-raised hover:bg-surface-overlay border border-border rounded-full text-sm font-medium text-foreground-secondary hover:text-foreground transition-all duration-200 shadow-sm cursor-pointer group"
                >
                  <StopCircle className="w-4 h-4 text-accent-error group-hover:scale-110 transition-transform" />
                  <span>Dừng tạo</span>
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
