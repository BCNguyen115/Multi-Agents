'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, User, ExternalLink, AlertTriangle } from 'lucide-react';
import { ChatMessage as ChatMessageType, SourceItem } from '../lib/types';
import { PEVStepper } from './PEVStepper';
import { SourcesList } from './SourcesList';
import { DynamicDashboard } from './dashboard/DynamicDashboard';
import { EnterpriseDashboard } from './EnterpriseDashboard';
import { DashboardSkeleton } from './dashboard/DashboardSkeleton';
import { DataSummaryView } from './DataSummaryView';

interface ChatMessageProps {
  message: ChatMessageType;
  isSending?: boolean;
  isLastMessage?: boolean;
  activeCSV?: { metadata: any } | null;
  onGenerateDashboard?: (prompt?: string) => void;
}

function extractWebSourcesFromMarkdown(content: string): SourceItem[] {
  const linkRegex = /\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g;
  const webSources: SourceItem[] = [];
  const seenUrls = new Set<string>();

  let match;
  while ((match = linkRegex.exec(content)) !== null) {
    const title = match[1].trim();
    const url = match[2].trim();
    if (!seenUrls.has(url) && title && url) {
      seenUrls.add(url);
      try {
        const domain = new URL(url).hostname.replace(/^www\./, '');
        webSources.push({
          file: url,
          section: title,
          category: 'search',
          url,
          title,
          domain,
        });
      } catch {
        webSources.push({
          file: url,
          section: title,
          category: 'search',
          url,
          title,
        });
      }
    }
  }
  return webSources;
}

export const ChatMessage: React.FC<ChatMessageProps> = ({
  message,
  isSending,
  isLastMessage,
  activeCSV,
  onGenerateDashboard,
}) => {
  let displayAnswer = message.content;
  let parsedSources: SourceItem[] = message.sources || [];

  // Per-message loading state
  const isThisMessageLoading =
    message.status === 'loading' ||
    (!message.dashboardSpec && !message.generatedCode && isLastMessage && Boolean(isSending));

  // Parse JSON response if wrapped in JSON string { "explanation": "...", ... }
  if (message.role === 'assistant' && message.content && typeof message.content === 'string') {
    const trimmed = message.content.trim();
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
      try {
        const parsed = JSON.parse(trimmed);
        if (parsed && typeof parsed === 'object') {
          const extractedText =
            parsed.explanation ||
            parsed.content ||
            parsed.answer ||
            parsed.response ||
            parsed.text;
          if (extractedText && typeof extractedText === 'string') {
            displayAnswer = extractedText;
          }
          if (Array.isArray(parsed.sources)) {
            parsedSources = parsed.sources;
          }
        }
      } catch {
        // Content is plain string or invalid JSON snippet, fallback to raw content
      }
    }
  }

  // If no explicit sources passed in payload, extract web sources from Markdown text
  if (displayAnswer && parsedSources.length === 0) {
    const extractedWebSources = extractWebSourcesFromMarkdown(displayAnswer);
    if (extractedWebSources.length > 0) {
      parsedSources = extractedWebSources;
    }
  }

  // Check if assistant response is a Data Agent summary request
  const isDataSummary =
    message.role === 'assistant' &&
    !message.dashboardSpec &&
    Boolean(displayAnswer) &&
    (message.agentMode?.includes('Data Agent') ||
      displayAnswer.includes('Tóm Tắt Dữ Liệu') ||
      displayAnswer.includes('Chỉ Số Tổng Quan') ||
      displayAnswer.includes('Thông Tin Tập Dữ Liệu') ||
      displayAnswer.includes('Số thuộc tính (cột)') ||
      displayAnswer.includes('Số bản ghi (dòng)'));

  if (message.role === 'user') {
    return (
      <div className="flex items-start justify-end gap-3 my-3 w-full">
        <div className="max-w-[80%] bg-gradient-to-r from-[#005697] to-[#F37021] text-white px-5 py-2.5 rounded-2xl rounded-tr-sm shadow-sm text-sm font-medium leading-relaxed whitespace-pre-wrap">
          {displayAnswer}
        </div>
        <div className="w-9 h-9 rounded-full bg-slate-800 text-white flex items-center justify-center shrink-0 shadow-sm">
          <User className="w-5 h-5" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start justify-start gap-3 my-4 w-full">
      {/* Agent Avatar Icon */}
      <div className="w-9 h-9 rounded-full bg-gradient-to-r from-[#005697] to-[#F37021] p-0.5 flex items-center justify-center shrink-0 shadow-sm">
        <div className="w-full h-full rounded-full bg-transparent flex items-center justify-center">
          <Bot className="w-5 h-5 text-white" />
        </div>
      </div>

      <div className="flex-1 max-w-4xl bg-white dark:bg-slate-900 border border-slate-200/90 dark:border-slate-800 rounded-2xl rounded-tl-none p-5 shadow-sm space-y-4 text-slate-900 dark:text-slate-100">
        {/* PEV Loop Stepper for Assistant Messages */}
        {(message.pevStep || message.pevEvents || message.pevTrace || (isThisMessageLoading && isSending)) && (
          <PEVStepper
            pevStep={message.pevStep}
            pevEvents={message.pevEvents}
            pevTrace={message.pevTrace}
            isStreaming={isThisMessageLoading && Boolean(isSending) && !displayAnswer}
          />
        )}

        {/* Data Summary View (4 visual blocks for CSV/Data Agent responses) */}
        {isDataSummary && displayAnswer ? (
          <DataSummaryView
            totalRows={
              activeCSV?.metadata?.totalRows ||
              activeCSV?.metadata?.total_rows ||
              message.metadata?.total_rows ||
              message.metadata?.totalRows
            }
            totalCols={
              activeCSV?.metadata?.totalColumns ||
              activeCSV?.metadata?.total_cols ||
              message.metadata?.total_cols ||
              message.metadata?.totalColumns
            }
            columns={
              Array.isArray(activeCSV?.metadata?.columns)
                ? activeCSV.metadata.columns.map((c: any) =>
                    typeof c === 'string' ? c : (c.name || c.field || c.headerName || String(c))
                  )
                : Array.isArray(message.metadata?.columns)
                ? message.metadata.columns.map((c: any) =>
                    typeof c === 'string' ? c : (c.name || c.field || c.headerName || String(c))
                  )
                : undefined
            }
            markdownContent={displayAnswer}
            message={message}
            metadata={message.metadata}
            onGenerateDashboard={
              onGenerateDashboard
                ? () => onGenerateDashboard('Dựng dashboard trực quan từ dữ liệu này')
                : undefined
            }
          />
        ) : displayAnswer ? (
          /* Default Message Text Content with React Markdown */
          <div className="font-sans text-sm text-slate-900 dark:text-slate-100 leading-relaxed">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h3({ children }) {
                  return (
                    <h3 className="border-l-4 border-blue-500 font-bold pl-3 my-3 text-slate-900 dark:text-slate-100 text-base leading-snug">
                      {children}
                    </h3>
                  );
                },
                h1({ children }) {
                  return (
                    <h1 className="text-xl font-extrabold text-slate-900 dark:text-slate-100 my-3">
                      {children}
                    </h1>
                  );
                },
                h2({ children }) {
                  return (
                    <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100 border-l-4 border-blue-400 pl-2.5 my-3">
                      {children}
                    </h2>
                  );
                },
                ul({ children }) {
                  return (
                    <ul className="list-disc pl-5 my-2 space-y-1.5 marker:text-blue-500 text-slate-800 dark:text-slate-200">
                      {children}
                    </ul>
                  );
                },
                ol({ children }) {
                  return (
                    <ol className="list-decimal pl-5 my-2 space-y-1.5 text-slate-800 dark:text-slate-200">
                      {children}
                    </ol>
                  );
                },
                li({ children }) {
                  return <li className="leading-relaxed text-sm">{children}</li>;
                },
                strong({ children }) {
                  return (
                    <strong className="font-semibold text-slate-900 dark:text-slate-100 bg-blue-50 dark:bg-blue-950/40 px-1 py-0.5 rounded border border-blue-100 dark:border-blue-900/30">
                      {children}
                    </strong>
                  );
                },
                a({ href, children }) {
                  return (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-0.5 text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 underline font-medium hover:bg-blue-50 dark:hover:bg-blue-950/50 px-1 rounded transition-colors"
                    >
                      {children}
                      <ExternalLink className="w-3 h-3 ml-0.5 inline shrink-0" />
                    </a>
                  );
                },
                p({ children }) {
                  return (
                    <p className="my-2 leading-relaxed text-slate-800 dark:text-slate-200 text-sm">
                      {children}
                    </p>
                  );
                },
                code({ className, children, ...props }) {
                  const isInline = !className;
                  if (isInline) {
                    return (
                      <code
                        className="bg-slate-100 dark:bg-slate-800 text-pink-600 dark:text-pink-400 px-1.5 py-0.5 rounded text-xs font-mono"
                        {...props}
                      >
                        {children}
                      </code>
                    );
                  }
                  return (
                    <pre className="bg-slate-900 text-slate-100 p-3.5 rounded-xl overflow-x-auto my-3 text-xs font-mono shadow-inner">
                      <code className={className} {...props}>
                        {children}
                      </code>
                    </pre>
                  );
                },
              }}
            >
              {displayAnswer}
            </ReactMarkdown>
          </div>
        ) : null}

        {/* Dashboard skeleton OR static dashboard OR unverified warning banner */}
        {isThisMessageLoading && message.role === 'assistant' && (message.agentMode?.includes('Data Agent') || !displayAnswer) ? (
          <DashboardSkeleton />
        ) : message.dashboardSpec ? (
          <DynamicDashboard spec={message.dashboardSpec} />
        ) : activeCSV && message.generatedCode ? (
          <EnterpriseDashboard
            metadata={activeCSV.metadata}
            generatedCode={message.generatedCode}
          />
        ) : !isThisMessageLoading && !message.dashboardSpec && (message.pevTrace?.is_verified === false || message.pevTrace?.verifier?.is_verified === false || message.pevEvents?.verifying?.is_verified === false) ? (
          <div className="my-3 p-3.5 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded-xl text-amber-800 dark:text-amber-300 text-xs flex items-center gap-2.5 font-medium shadow-xs">
            <AlertTriangle className="w-4.5 h-4.5 text-amber-600 dark:text-amber-400 shrink-0" />
            <span>Không thể khởi tạo Dashboard do dữ liệu không phù hợp với yêu cầu kiểm duyệt (Verifier).</span>
          </div>
        ) : null}

        {/* Enterprise Document & Web Citation Sources Grid */}
        {parsedSources.length > 0 && (
          <SourcesList sources={parsedSources} />
        )}
      </div>
    </div>
  );
};
