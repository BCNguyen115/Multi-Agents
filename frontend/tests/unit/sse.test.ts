import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchSSEStream } from '../../lib/sse';

const sse = (...events: Array<[string, unknown]>) =>
  events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join('');

/** A response whose body arrives in the given pieces (so events can be split across network chunks). */
const streamOf = (pieces: string[], status = 200) =>
  new Response(
    new ReadableStream({
      start(controller) {
        const encoder = new TextEncoder();
        pieces.forEach((piece) => controller.enqueue(encoder.encode(piece)));
        controller.close();
      },
    }),
    { status, headers: { 'Content-Type': 'text/event-stream' } },
  );

afterEach(() => vi.unstubAllGlobals());

describe('fetchSSEStream answer streaming', () => {
  it('delivers the answer tokens in order, then the verified final response', async () => {
    const body = sse(
      ['answer_delta', { text: 'Thời hạn ' }],
      ['answer_delta', { text: 'là 2 năm.' }],
      ['final_response', { response: 'Thời hạn là 2 năm [1].', target_agent: 'rag_agent', is_verified: true }],
    );
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamOf([body])));
    const seen: string[] = [];
    await fetchSSEStream('q', 's1', 'rag_agent', {
      onAnswerDelta: (text) => seen.push(`delta:${text}`),
      onAnswerReset: () => seen.push('reset'),
      onFinalResponse: (data) => seen.push(`final:${data.response}`),
    });
    expect(seen).toEqual(['delta:Thời hạn ', 'delta:là 2 năm.', 'final:Thời hạn là 2 năm [1].']);
  });

  it('forwards a reset and copes with an event split across two network chunks', async () => {
    const whole = sse(['answer_delta', { text: 'một' }], ['answer_reset', {}], ['answer_delta', { text: 'hai' }]);
    const cut = whole.indexOf('answer_reset') + 4; // in the middle of an event name
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamOf([whole.slice(0, cut), whole.slice(cut)])));
    const seen: string[] = [];
    await fetchSSEStream('q', 's1', null, {
      onAnswerDelta: (text) => seen.push(text),
      onAnswerReset: () => seen.push('reset'),
    });
    expect(seen).toEqual(['một', 'reset', 'hai']);
  });

  it('reports an expired session instead of reading a body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 401 })));
    const errors: string[] = [];
    await fetchSSEStream('q', 's1', null, { onError: (message) => errors.push(message) });
    expect(errors[0]).toContain('đăng nhập');
  });
});
