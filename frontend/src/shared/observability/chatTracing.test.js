import { SpanStatusCode } from '@opentelemetry/api';
import { describe, expect, it, vi } from 'vitest';

import { ChatStreamTrace } from './chatTracing.js';

function fakeSpan() {
  return {
    addEvent: vi.fn(),
    end: vi.fn(),
    setAttribute: vi.fn(),
    setAttributes: vi.fn(),
    setStatus: vi.fn(),
  };
}

describe('ChatStreamTrace', () => {
  it('records milestones without attaching streamed content', () => {
    const span = fakeSpan();
    let now = 10;
    const tracing = new ChatStreamTrace(span, () => now);

    now = 20;
    tracing.responseHeaders(
      new Response(null, {
        status: 200,
        headers: { 'X-Request-ID': 'request-123' },
      }),
    );
    now = 30;
    tracing.event({
      type: 'meta',
      conversation_id: 'conversation-1',
      run_id: 'run-1',
    });
    now = 45;
    tracing.event({ type: 'token', delta: '敏感的回答内容' });
    now = 60;
    tracing.event({ type: 'token', delta: '不会重复首字耗时' });
    tracing.event({ type: 'done', outcome: 'completed', message_id: 'm-1' });
    tracing.end();

    expect(span.setAttribute).toHaveBeenCalledOnce();
    expect(span.setAttribute).toHaveBeenCalledWith(
      'chat.first_token.duration_ms',
      35,
    );
    expect(span.setStatus).toHaveBeenCalledWith({ code: SpanStatusCode.OK });
    expect(span.end).toHaveBeenCalledOnce();
    expect(JSON.stringify(span.addEvent.mock.calls)).not.toContain(
      '敏感的回答内容',
    );
  });

  it('classifies an unterminated stream as a disconnected error', () => {
    const span = fakeSpan();
    const tracing = new ChatStreamTrace(span, () => 10);

    tracing.streamClosed();
    tracing.end();

    expect(span.setAttributes).toHaveBeenCalledWith({
      'chat.outcome': 'disconnected',
      'error.type': 'UnknownError',
    });
    expect(span.setStatus).toHaveBeenCalledWith({
      code: SpanStatusCode.ERROR,
    });
  });

  it('records cancellation without marking the span as an error', () => {
    const span = fakeSpan();
    const tracing = new ChatStreamTrace(span, () => 10);

    tracing.cancel();
    tracing.end();

    expect(span.setAttribute).toHaveBeenCalledWith(
      'chat.outcome',
      'cancelled',
    );
    expect(span.setStatus).not.toHaveBeenCalled();
  });
});
