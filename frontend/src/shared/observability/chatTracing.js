import {
  context,
  SpanKind,
  SpanStatusCode,
  trace,
} from '@opentelemetry/api';

import { env } from '../config/env.js';

const TRACER_NAME = 'smartserve.web.chat';

export function startChatStreamTrace({ operation, path }) {
  if (!env.observabilityEnabled) return NOOP_CHAT_STREAM_TRACE;

  const span = trace.getTracer(TRACER_NAME).startSpan('chat.stream', {
    kind: SpanKind.CLIENT,
    attributes: {
      'chat.operation': operation,
      'http.request.method': 'POST',
      'url.path': path,
    },
  });
  return new ChatStreamTrace(span);
}

export class ChatStreamTrace {
  constructor(span, now = monotonicNow) {
    this.span = span;
    this.now = now;
    this.startedAt = now();
    this.firstTokenSeen = false;
    this.terminalEventSeen = false;
    this.ended = false;
    this.span.addEvent('chat.request.started');
  }

  run(callback) {
    const spanContext = trace.setSpan(context.active(), this.span);
    return context.with(spanContext, callback);
  }

  responseHeaders(response) {
    const requestId = response.headers.get('X-Request-ID');
    this.span.setAttributes({
      'http.response.status_code': response.status,
      ...(requestId ? { 'app.request_id': requestId } : {}),
    });
    this.addMilestone('chat.response.headers');
  }

  event(event) {
    if (!event || typeof event !== 'object') return;

    if (event.type === 'meta') {
      this.span.setAttributes({
        ...(event.run_id ? { 'app.run_id': event.run_id } : {}),
        ...(event.conversation_id
          ? { 'app.conversation_id': event.conversation_id }
          : {}),
      });
      this.addMilestone('chat.meta.received');
      return;
    }

    if (
      event.type === 'token' &&
      event.delta &&
      !this.firstTokenSeen
    ) {
      this.firstTokenSeen = true;
      const elapsed = this.elapsedMilliseconds();
      this.span.setAttribute('chat.first_token.duration_ms', elapsed);
      this.span.addEvent('chat.first_token', {
        'chat.elapsed_ms': elapsed,
      });
      return;
    }

    if (event.type === 'done') {
      this.terminalEventSeen = true;
      const outcome = event.outcome || 'completed';
      this.span.setAttributes({
        'chat.outcome': outcome,
        ...(event.message_id ? { 'app.message_id': event.message_id } : {}),
      });
      this.span.setStatus({ code: SpanStatusCode.OK });
      this.addMilestone('chat.done');
      return;
    }

    if (event.type === 'error') {
      this.terminalEventSeen = true;
      const errorType = boundedErrorType(event.code);
      this.span.setAttributes({
        'chat.outcome': 'error',
        'error.type': errorType,
      });
      this.span.setStatus({ code: SpanStatusCode.ERROR });
      this.addMilestone('chat.error', { 'error.type': errorType });
    }
  }

  cancel() {
    this.terminalEventSeen = true;
    this.span.setAttribute('chat.outcome', 'cancelled');
    this.addMilestone('chat.cancelled');
  }

  fail(error, outcome = 'error') {
    this.terminalEventSeen = true;
    const errorType = boundedErrorType(error?.code || error?.name);
    this.span.setAttributes({
      'chat.outcome': outcome,
      'error.type': errorType,
    });
    this.span.setStatus({ code: SpanStatusCode.ERROR });
    this.addMilestone(`chat.${outcome}`, { 'error.type': errorType });
  }

  streamClosed() {
    if (!this.terminalEventSeen) this.fail(null, 'disconnected');
  }

  end() {
    if (this.ended) return;
    this.ended = true;
    this.span.end();
  }

  addMilestone(name, attributes = {}) {
    this.span.addEvent(name, {
      'chat.elapsed_ms': this.elapsedMilliseconds(),
      ...attributes,
    });
  }

  elapsedMilliseconds() {
    return Math.max(0, this.now() - this.startedAt);
  }
}

const NOOP_CHAT_STREAM_TRACE = Object.freeze({
  run: (callback) => callback(),
  responseHeaders: () => {},
  event: () => {},
  cancel: () => {},
  fail: () => {},
  streamClosed: () => {},
  end: () => {},
});

function monotonicNow() {
  return typeof performance === 'undefined' ? Date.now() : performance.now();
}

function boundedErrorType(value) {
  const candidate = String(value || 'UnknownError');
  return /^[A-Za-z0-9_.:-]{1,128}$/.test(candidate)
    ? candidate
    : 'UnknownError';
}
