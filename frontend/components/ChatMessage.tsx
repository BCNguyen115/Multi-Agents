'use client';

import React, { useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import { t, useLang } from '../lib/i18n';
import remarkGfm from 'remark-gfm';
import { Bot, User, ExternalLink, AlertTriangle, Copy, Check, Loader2, ShieldCheck, ShieldAlert, Hourglass } from 'lucide-react';
import { ChatMessage as ChatMessageType, SourceItem, CSVMetadata } from '../lib/types';
import { PEVStepper } from './PEVStepper';
import { SourcesList } from './SourcesList';
import { DynamicDashboard } from './dashboard/DynamicDashboard';
import { EnterpriseDashboard } from './EnterpriseDashboard';
import { DashboardSkeleton } from './dashboard/DashboardSkeleton';
import { DataSummaryView } from './DataSummaryView';
import { ApprovalCard } from './ApprovalCard';
import { KnowledgeDocumentsCard } from './KnowledgeDocumentsCard';

interface ChatMessageProps {
  message: ChatMessageType;
  userQuery?: string;
  isSending?: boolean;
  isLastMessage?: boolean;
  activeCSV?: { file?: File; metadata: CSVMetadata; tableName?: string } | null;
  onGenerateDashboard?: (prompt?: string) => void;
}

const DASHBOARD_INTENT_REGEX = /(?:dashboard|biểu đồ|bảng điều khiển|chart|vẽ|visualize|visualization|trực quan|trực quan hóa|plot|đồ thị)/i;

function isDataAgentTarget(message: ChatMessageType): boolean {
  // Check explicit target from SSE plan / executing / final_response events or pevTrace
  const sseTarget =
    message.pevEvents?.plan?.target_agent ||
    message.pevEvents?.executing?.target_agent ||
    message.pevEvents?.final_response?.target_agent ||
    message.pevTrace?.planner?.target_agent ||
    message.pevTrace?.executor?.agent_used;

  if (sseTarget) {
    return sseTarget.toLowerCase().includes('data');
  }

  // If no SSE target yet, check message.agentMode
  if (message.agentMode) {
    const mode = message.agentMode.toLowerCase();
    if (mode.includes('search') || mode.includes('rag') || mode.includes('db_agent') || mode.includes('integration')) {
      return false;
    }
    return mode.includes('data');
  }

  return false;
}

type VerificationKind = 'rag' | 'data' | 'db' | 'other';

/** Verdict of the Verifier for a finished message: `true`/`false`, or `null` when the message carries none. */
function verifierVerdict(message: ChatMessageType): boolean | null {
  const candidates = [
    message.pevEvents?.final_response?.is_verified,
    message.pevTrace?.verifier?.is_verified,
    message.pevTrace?.is_verified,
    message.pevEvents?.verifying?.is_verified,
  ];
  const found = candidates.find((v) => typeof v === 'boolean');
  return typeof found === 'boolean' ? found : null;
}

function verificationKind(message: ChatMessageType): VerificationKind {
  const target = (
    message.pevEvents?.final_response?.target_agent ||
    message.pevEvents?.plan?.target_agent ||
    message.pevTrace?.executor?.agent_used ||
    message.pevTrace?.planner?.target_agent ||
    message.agentMode ||
    ''
  ).toLowerCase();
  if (target.includes('rag')) return 'rag';
  if (target.includes('data_agent') || target.includes('data agent')) return 'data';
  if (target.includes('db')) return 'db';
  return 'other';
}

/** One status line at the top of a text answer: preview, verified or not verified, with what the check covered. */
function VerificationStrip({ message, loading }: { message: ChatMessageType; loading: boolean }) {
  const [lang] = useLang();
  const verdict = message.isPreview || loading ? null : verifierVerdict(message);
  if (!message.isPreview && verdict === null) return null;

  const state = message.isPreview ? 'preview' : verdict ? 'verified' : 'unverified';
  const Icon = state === 'preview' ? Hourglass : state === 'verified' ? ShieldCheck : ShieldAlert;
  const tone =
    state === 'verified' ? 'text-accent-verifier' : state === 'unverified' ? 'text-accent-error' : 'text-foreground-muted';
  const label = state === 'preview' ? t(lang, 'answer.preview') : t(lang, state === 'verified' ? 'verify.verified' : 'verify.unverified');

  return (
    <div className="mb-2 text-xs">
      <p role="status" aria-live="polite" className={`inline-flex items-center gap-1.5 font-semibold ${tone}`}>
        <Icon className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
        <span>{label}</span>
      </p>
      {state !== 'preview' && (
        <details className="mt-1 text-foreground-secondary">
          <summary className="cursor-pointer w-fit rounded font-medium hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary/40">
            {t(lang, 'verify.whatChecked')}
          </summary>
          <p className="mt-1 leading-relaxed">{t(lang, `verify.detail.${verificationKind(message)}`)}</p>
        </details>
      )}
    </div>
  );
}

function hasDashboardIntent(userQuery?: string, message?: ChatMessageType): boolean {
  if (userQuery && DASHBOARD_INTENT_REGEX.test(userQuery)) {
    return true;
  }
  if (message?.dashboardSpec || message?.generatedCode) {
    return true;
  }
  return false;
}


function extractWebSourcesFromMarkdown(content: string): SourceItem[] {
  const linkRegex = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
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
        webSources.push({ file: url, section: title, category: 'search', url, title, domain });
      } catch {
        webSources.push({ file: url, section: title, category: 'search', url, title });
      }
    }
  }
  return webSources;
}

// Copy Code Button Component
function CopyCodeButton({ code }: { code: string }) {
  const [lang] = useLang();
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
      const textArea = document.createElement('textarea');
      textArea.value = code;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [code]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="p-1 rounded-md hover:bg-surface-overlay text-foreground-muted hover:text-foreground transition-all duration-150 cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-primary/50"
      title={copied ? t(lang, 'chat.copied') : t(lang, 'chat.copyCode')}
      aria-label={t(lang, 'chat.copyCode')}
    >
      {copied ? <Check className="w-3.5 h-3.5 text-accent-verifier" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  );
}

export const ChatMessage: React.FC<ChatMessageProps> = ({
  message,
  userQuery,
  isSending,
  isLastMessage,
  activeCSV,
  onGenerateDashboard,
}) => {
  const [lang] = useLang();
  let displayAnswer = message.content;
  let parsedSources: SourceItem[] = message.sources || [];
  let isSummaryReply = false; // the data agent labels its text summaries `type: "text_summary"`, whatever the language

  const isThisMessageLoading =
    message.status === 'loading' ||
    (!message.dashboardSpec && !message.generatedCode && isLastMessage && Boolean(isSending));

  const isTargetData = isDataAgentTarget(message);
  const isDashboardIntent = hasDashboardIntent(userQuery, message);
  const shouldRenderDashboardSkeleton =
    isThisMessageLoading && message.role === 'assistant' && isTargetData && isDashboardIntent;

  // Parse JSON response if wrapped
  if (message.role === 'assistant' && message.content && typeof message.content === 'string') {
    const trimmed = message.content.trim();
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
      try {
        const parsed = JSON.parse(trimmed);
        if (parsed && typeof parsed === 'object') {
          isSummaryReply = parsed.type === 'text_summary';
          const extractedText = parsed.explanation || parsed.content || parsed.answer || parsed.response || parsed.text;
          if (extractedText && typeof extractedText === 'string') {
            displayAnswer = extractedText;
          }
          if (Array.isArray(parsed.sources)) {
            parsedSources = parsed.sources;
          }
        }
      } catch {
        // fallback to raw content
      }
    }
  }

  if (displayAnswer && parsedSources.length === 0) {
    const extractedWebSources = extractWebSourcesFromMarkdown(displayAnswer);
    if (extractedWebSources.length > 0) {
      parsedSources = extractedWebSources;
    }
  }

  const isDataSummary =
    message.role === 'assistant' &&
    !message.dashboardSpec &&
    Boolean(displayAnswer) &&
    (message.agentMode?.includes('Data Agent') || isSummaryReply);

  // User message
  if (message.role === 'user') {
    return (
      <div className="flex items-start justify-end gap-3 my-3 w-full">
        <div className="max-w-[80%] bg-accent-primary text-white px-5 py-2.5 rounded-2xl rounded-tr-sm shadow-xs text-sm font-medium leading-relaxed whitespace-pre-wrap">
          {displayAnswer}
        </div>
        <div className="w-8 h-8 rounded-full bg-surface-raised border border-border text-foreground flex items-center justify-center shrink-0">
          <User className="w-4 h-4" />
        </div>
      </div>
    );
  }

  // Assistant message
  return (
    <div className="flex items-start justify-start gap-3 my-4 w-full">
      {/* Agent Avatar */}
      <div className="w-8 h-8 rounded-full bg-surface-raised border border-border flex items-center justify-center shrink-0">
        <div className="w-full h-full rounded-full bg-background flex items-center justify-center">
          <Bot className="w-4 h-4 text-accent-primary" />
        </div>
      </div>

      <div className="flex-1 max-w-4xl bg-surface border border-border rounded-2xl rounded-tl-none p-5 shadow-xs space-y-4 text-foreground">
        {/* PEV Loop Stepper */}
        {(message.pevStep || message.pevEvents || message.pevTrace || message.pevTraceState || (isThisMessageLoading && isSending)) && (
          <PEVStepper
            pevStep={message.pevStep}
            pevEvents={message.pevEvents}
            pevTrace={message.pevTrace}
            pevTraceState={message.pevTraceState}
            isStreaming={isThisMessageLoading && Boolean(isSending) && !displayAnswer}
          />
        )}

        {message.kind === 'knowledge-docs' && <KnowledgeDocumentsCard />}

        {/* Human-in-the-Loop Confirmation Card */}
        {message.approvalRequest && (
          <ApprovalCard
            approvalRequest={message.approvalRequest}
            sessionId={message.id}
          />
        )}

        {/* Data Summary View */}
        {isDataSummary && displayAnswer ? (
          <DataSummaryView
            totalRows={
              activeCSV?.metadata?.totalRows ||
              (activeCSV?.metadata as unknown as Record<string, unknown>)?.total_rows as number ||
              message.metadata?.total_rows ||
              message.metadata?.totalRows
            }
            totalCols={
              activeCSV?.metadata?.totalCols ||
              (activeCSV?.metadata as unknown as Record<string, unknown>)?.total_cols as number ||
              message.metadata?.total_cols ||
              message.metadata?.totalColumns
            }
            columns={
              Array.isArray(activeCSV?.metadata?.columns)
                ? activeCSV.metadata.columns.map((c) =>
                    typeof c === 'string' ? c : (c?.name || String(c))
                  )
                : Array.isArray(message.metadata?.columns)
                ? message.metadata.columns.map((c: string | Record<string, string>) =>
                    typeof c === 'string' ? c : ((c as Record<string, string>).name || (c as Record<string, string>).field || (c as Record<string, string>).headerName || String(c))
                  )
                : undefined
            }
            markdownContent={displayAnswer}
            message={message}
            metadata={message.metadata}
            onGenerateDashboard={
              onGenerateDashboard
                ? () => onGenerateDashboard(t(lang, 'chat.dashboardPrompt'))
                : undefined
            }
          />
        ) : displayAnswer ? (
          /* Markdown Content */
          <div className="font-sans text-sm text-foreground leading-relaxed" aria-busy={message.isPreview ? true : undefined}>
            <VerificationStrip message={message} loading={Boolean(isThisMessageLoading)} />
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1({ children }) {
                  return <h1 className="text-xl font-extrabold text-foreground my-3">{children}</h1>;
                },
                h2({ children }) {
                  return <h2 className="text-lg font-bold text-foreground my-3">{children}</h2>;
                },
                h3({ children }) {
                  return <h3 className="font-bold my-3 text-foreground text-base leading-snug">{children}</h3>;
                },
                ul({ children }) {
                  return <ul className="list-disc pl-5 my-2 space-y-1.5 marker:text-accent-primary text-foreground-secondary">{children}</ul>;
                },
                ol({ children }) {
                  return <ol className="list-decimal pl-5 my-2 space-y-1.5 text-foreground-secondary">{children}</ol>;
                },
                li({ children }) {
                  return <li className="leading-relaxed text-sm">{children}</li>;
                },
                strong({ children }) {
                  return (
                    <strong className="font-semibold text-foreground bg-accent-primary/8 px-1 py-0.5 rounded border border-accent-primary/15">
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
                      className="inline-flex items-center gap-0.5 text-accent-primary hover:text-accent-primary-hover underline font-medium hover:bg-accent-primary/5 px-1 rounded transition-colors"
                    >
                      {children}
                      <ExternalLink className="w-3 h-3 ml-0.5 inline shrink-0" />
                    </a>
                  );
                },
                p({ children }) {
                  return <p className="my-2 leading-relaxed text-foreground-secondary text-sm">{children}</p>;
                },
                table({ children }) {
                  return (
                    <div className="overflow-x-auto my-3.5 rounded-lg border border-border shadow-xs">
                      <table className="w-full text-xs border-collapse text-left">{children}</table>
                    </div>
                  );
                },
                thead({ children }) {
                  return <thead className="bg-surface-raised text-foreground font-bold border-b border-border uppercase tracking-wider text-xs">{children}</thead>;
                },
                tr({ children }) {
                  return <tr className="border-b border-border last:border-0 hover:bg-surface-raised/50 transition-colors">{children}</tr>;
                },
                th({ children }) {
                  return <th className="p-2.5 font-bold text-foreground">{children}</th>;
                },
                td({ children }) {
                  const textContent = String(children || '');
                  const isNumeric = /^-?\d[\d,.]*$/;
                  return (
                    <td className={`p-2.5 text-foreground-secondary ${isNumeric.test(textContent.trim()) ? 'font-mono text-right tabular-nums' : ''}`}>
                      {children}
                    </td>
                  );
                },
                code({ className, children, ...props }) {
                  const isInline = !className;
                  if (isInline) {
                    return (
                      <code className="bg-surface-raised text-accent-error px-1.5 py-0.5 rounded text-xs font-mono" {...props}>
                        {children}
                      </code>
                    );
                  }
                  const codeString = String(children).replace(/\n$/, '');
                  return (
                    <div className="relative group my-3.5 rounded-xl overflow-hidden border border-border shadow-xs">
                      {/* Code Block Header */}
                      <div className="flex items-center justify-between px-3.5 py-1.5 bg-surface-raised/80 border-b border-border text-xs font-mono text-foreground-muted select-none">
                        <span>{className ? className.replace('language-', '').toUpperCase() : 'CODE'}</span>
                        <CopyCodeButton code={codeString} />
                      </div>
                      {/* Theme-aware Code Content */}
                      <pre className="p-4 bg-surface-raised/40 text-foreground overflow-x-auto text-xs font-mono leading-relaxed">
                        <code className={className} {...props}>
                          {children}
                        </code>
                      </pre>
                    </div>
                  );
                },
              }}
            >
              {displayAnswer}
            </ReactMarkdown>
          </div>
        ) : null}

        {/* Loading skeleton / Dashboard / Fallback spinner / Unverified warning */}
        {shouldRenderDashboardSkeleton ? (
          <DashboardSkeleton />
        ) : isThisMessageLoading && !displayAnswer ? (
          <div className="flex items-center gap-2.5 text-xs text-foreground-muted py-2 animate-pulse">
            <Loader2 className="w-4 h-4 animate-spin text-accent-primary" />
            <span>{t(lang, 'chat.processing')}</span>
          </div>
        ) : message.dashboardSpec ? (
          <DynamicDashboard spec={message.dashboardSpec} />
        ) : activeCSV && message.generatedCode ? (
          <EnterpriseDashboard
            metadata={activeCSV.metadata as import('../lib/types').CSVMetadata}
            generatedCode={message.generatedCode}
          />
        ) : !isThisMessageLoading && !message.dashboardSpec && (message.pevTrace?.is_verified === false || message.pevTrace?.verifier?.is_verified === false || message.pevEvents?.verifying?.is_verified === false) ? (
          <div className="my-3 p-3.5 bg-accent-error/5 border border-accent-error/20 rounded-xl text-accent-error text-xs flex items-center gap-2.5 font-medium">
            <AlertTriangle className="w-4.5 h-4.5 shrink-0" />
            <span>{t(lang, 'chat.blocked')}</span>
          </div>
        ) : null}


        {/* Sources */}
        {parsedSources.length > 0 && <SourcesList sources={parsedSources} />}
      </div>
    </div>
  );
};
