import { env } from '../../shared/config/env.js';
import { tokenStorage } from '../../shared/storage/tokenStorage.js';
import { errorFromResponse } from '../../shared/api/http.js';
import { startChatStreamTrace } from '../../shared/observability/chatTracing.js';

export const conversationApi = {
  async list() {
    return authenticatedJson('/conversations');
  },
  async messages(id) {
    return authenticatedJson(
      `/conversations/${encodeURIComponent(id)}/messages`,
    );
  },
  async remove(id) {
    return authenticatedJson(`/conversations/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
  },
};

export async function streamChat(payload, { signal, onEvent }) {
  return streamEndpoint('/chat/stream', payload, {
    signal,
    onEvent,
    operation: 'send',
  });
}

export async function resumeChat(
  payload,
  { signal, onEvent, idempotencyKey },
) {
  return streamEndpoint('/chat/resume', payload, {
    signal,
    onEvent,
    operation: 'resume',
    extraHeaders: { 'Idempotency-Key': idempotencyKey },
  });
}

async function streamEndpoint(
  path,
  payload,
  { signal, onEvent, operation, extraHeaders = {} },
) {
  const streamTrace = startChatStreamTrace({ operation, path });
  let response;
  return streamTrace.run(async () => {
    try {
      try {
        response = await fetch(`${env.apiBaseUrl}${path}`, {
          method: 'POST',
          signal,
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokenStorage.get() || ''}`,
            ...extraHeaders,
          },
          body: JSON.stringify(payload),
        });
      } catch (error) {
        if (error.name === 'AbortError') throw error;
        const networkError = new Error('网络连接失败');
        networkError.cause = error;
        throw networkError;
      }
      streamTrace.responseHeaders(response);
      if (!response.ok) {
        throw errorFromResponse(
          response,
          await response.json().catch(() => null),
        );
      }
      if (!response.body) throw new Error('浏览器不支持流式响应');

      const parser = createSseParser((event) => {
        streamTrace.event(event);
        onEvent(event);
      });
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        parser.push(decoder.decode(value, { stream: true }));
      }
      parser.push(decoder.decode());
      parser.finish();
      streamTrace.streamClosed();
    } catch (error) {
      if (error.name === 'AbortError') streamTrace.cancel();
      else streamTrace.fail(error);
      throw error;
    } finally {
      streamTrace.end();
    }
  });
}

export function createSseParser(onEvent) {
  let buffer = '';
  const consume = (block) => {
    const data = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n');
    if (!data) return;
    try {
      onEvent(JSON.parse(data));
    } catch {
      /* ignore malformed event */
    }
  };
  return {
    push(text) {
      buffer += text;
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() || '';
      blocks.forEach(consume);
    },
    finish() {
      if (buffer.trim()) consume(buffer);
      buffer = '';
    },
  };
}

async function authenticatedJson(path, options = {}) {
  const response = await fetch(`${env.apiBaseUrl}${path}`, {
    ...options,
    headers: { Authorization: `Bearer ${tokenStorage.get() || ''}` },
  });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw errorFromResponse(response, body);
  return body;
}
