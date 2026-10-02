import { isUnauthorized } from './authClient';
import { HumanApprovalRequest, PEVEventData, PEVStepData, PEVTrace } from './types';
import { getLang, t } from './i18n';
import { apiFetch } from './apiFetch';

export interface StreamCallbacks {
  onPevStep?: (data: PEVStepData) => void;
  onPlan?: (data: { plan: string; target_agent: string }) => void;
  onExecuting?: (data: { target_agent: string; execution_result?: string; status?: string; message?: string }) => void;
  onVerifying?: (data: { is_verified: boolean; verifier_feedback: string; retry_count: number }) => void;
  onHumanApprovalRequired?: (data: HumanApprovalRequest) => void;
  onFinalResponse?: (data: { response: string; target_agent: string; is_verified: boolean; pev_trace?: PEVTrace }) => void;
  /** More text of the answer being written (a preview until `onFinalResponse` brings the verified one). */
  onAnswerDelta?: (text: string) => void;
  /** The attempt is being redone (the Verifier asked for a correction): drop the preview. */
  onAnswerReset?: () => void;
  onError?: (error: string) => void;
}

/**
 * Fetch SSE stream from the backend with AbortController support and strict protocol boundary parsing.
 *
 * @param query - User query text
 * @param sessionId - Session correlation ID
 * @param agentMode - Optional forced agent mode
 * @param callbacks - Stream event callbacks
 * @param abortSignal - Optional AbortSignal for cancellation
 */
export async function fetchSSEStream(
  query: string,
  sessionId: string,
  agentMode: string | null,
  callbacks: StreamCallbacks,
  abortSignal?: AbortSignal,
  targetAgent?: string | null
): Promise<void> {
  const resolvedTarget = targetAgent || agentMode || null;
  const payload = {
    query,
    session_id: sessionId,
    agent_mode: agentMode,
    target_agent: resolvedTarget,
  };

  try {
    const response = await apiFetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(payload),
      signal: abortSignal,
    });

    if (!response.ok) {
      if (isUnauthorized(response)) throw new Error(t(getLang(), 'session.expiredRedirect'));
      throw new Error(`Server returned status ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error('No readable stream received');

    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    const dispatchEvent = (eventType: string, rawData: string) => {
      if (!rawData.trim()) return;
      try {
        const parsedData: PEVEventData = JSON.parse(rawData);

        if (eventType === 'pev_step' && callbacks.onPevStep) {
          callbacks.onPevStep({
            step: parsedData.step || 'planner',
            status: (parsedData.status as PEVStepData['status']) || 'active',
            target: parsedData.target || parsedData.target_agent || '',
            logs: parsedData.logs || parsedData.message || '',
            feedback: parsedData.feedback || '',
          });
        } else if (eventType === 'plan' && callbacks.onPlan) {
          callbacks.onPlan({
            plan: parsedData.plan || '',
            target_agent: parsedData.target_agent || parsedData.target || '',
          });
        } else if (eventType === 'executing' && callbacks.onExecuting) {
          callbacks.onExecuting({
            target_agent: parsedData.target_agent || parsedData.target || '',
            execution_result: parsedData.execution_result,
            status: parsedData.status,
            message: parsedData.message,
          });
        } else if (eventType === 'verifying' && callbacks.onVerifying) {
          callbacks.onVerifying({
            is_verified: parsedData.is_verified ?? false,
            verifier_feedback: parsedData.verifier_feedback || parsedData.feedback || '',
            retry_count: parsedData.retry_count ?? 0,
          });
        } else if (eventType === 'human_approval_required' && callbacks.onHumanApprovalRequired) {
          callbacks.onHumanApprovalRequired(parsedData as any);
        } else if (eventType === 'final_response' && callbacks.onFinalResponse) {
          callbacks.onFinalResponse({
            response: parsedData.response || '',
            target_agent: parsedData.target_agent || parsedData.target || '',
            is_verified: parsedData.is_verified ?? true,
            pev_trace: parsedData.pev_trace,
          });
        } else if (eventType === 'answer_delta' && callbacks.onAnswerDelta) {
          callbacks.onAnswerDelta(parsedData.text || '');
        } else if (eventType === 'answer_reset' && callbacks.onAnswerReset) {
          callbacks.onAnswerReset();
        } else if (eventType === 'error' && callbacks.onError) {
          callbacks.onError(parsedData.error || 'Stream error');
        }
      } catch {
        // Fallback for raw string data
        if (eventType === 'final_response' && callbacks.onFinalResponse) {
          callbacks.onFinalResponse({
            response: rawData,
            target_agent: '',
            is_verified: true,
          });
        }
      }
    };

    try {
      while (true) {
        if (abortSignal?.aborted) {
          reader.cancel();
          break;
        }

        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Normalize CRLF to LF
        buffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

        // SSE messages are separated by double newlines (\n\n)
        let boundaryIndex: number;
        while ((boundaryIndex = buffer.indexOf('\n\n')) !== -1) {
          const messageBlock = buffer.slice(0, boundaryIndex);
          buffer = buffer.slice(boundaryIndex + 2);

          if (!messageBlock.trim()) continue;

          let eventType = 'message';
          const dataParts: string[] = [];

          const lines = messageBlock.split('\n');
          for (const rawLine of lines) {
            const line = rawLine.trim();
            if (!line || line.startsWith(':')) {
              // Ignore comments and pings
              continue;
            }
            if (line.startsWith('event:')) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith('data:')) {
              dataParts.push(line.slice(5).trim());
            }
          }

          if (dataParts.length > 0) {
            dispatchEvent(eventType, dataParts.join('\n'));
          }
        }
      }

      // Handle any trailing message in buffer
      if (buffer.trim()) {
        let eventType = 'message';
        const dataParts: string[] = [];
        const lines = buffer.split('\n');
        for (const rawLine of lines) {
          const line = rawLine.trim();
          if (!line || line.startsWith(':')) continue;
          if (line.startsWith('event:')) {
            eventType = line.slice(6).trim();
          } else if (line.startsWith('data:')) {
            dataParts.push(line.slice(5).trim());
          }
        }
        if (dataParts.length > 0) {
          dispatchEvent(eventType, dataParts.join('\n'));
        }
      }
    } finally {
      try {
        reader.releaseLock();
      } catch {
        // Reader may already be released
      }
    }
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      return;
    }
    if (callbacks.onError) {
      callbacks.onError(err.message || 'Stream connection error');
    }
  }
}
