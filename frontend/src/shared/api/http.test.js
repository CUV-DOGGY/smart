import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiClientError, http } from './http.js';

afterEach(() => vi.unstubAllGlobals());

describe('http', () => {
  it('normalizes the public API error contract', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            code: 'VALIDATION_ERROR',
            message: '请求参数校验失败',
            field_errors: [{ field: 'username', message: '长度不足' }],
            request_id: 'request-123',
          }),
          { status: 422, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    );

    await expect(http('/test')).rejects.toMatchObject({
      name: 'ApiClientError',
      status: 422,
      code: 'VALIDATION_ERROR',
      requestId: 'request-123',
    });
  });

  it('uses a safe network error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('secret host')));
    await expect(http('/test')).rejects.toBeInstanceOf(ApiClientError);
    await expect(http('/test')).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
    });
  });

  it('distinguishes a client timeout from a generic network error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((_, { signal }) =>
        new Promise((_, reject) => {
          signal.addEventListener('abort', () => reject(new Error('aborted')));
        }),
      ),
    );

    await expect(http('/test', { timeoutMs: 5 })).rejects.toMatchObject({
      code: 'REQUEST_TIMEOUT',
    });
  });

  it('exposes Retry-After to feature-specific retry policies', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ code: 'DATABASE_UNAVAILABLE' }), {
          status: 503,
          headers: {
            'Content-Type': 'application/json',
            'Retry-After': '2',
          },
        }),
      ),
    );

    await expect(http('/test')).rejects.toMatchObject({
      status: 503,
      retryAfterMs: 2000,
    });
  });
});
