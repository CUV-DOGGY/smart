import { env } from '../config/env.js';
import { tokenStorage } from '../storage/tokenStorage.js';

let unauthorizedHandler = null;

export class ApiClientError extends Error {
  constructor({
    status = 0,
    code = 'NETWORK_ERROR',
    message = '网络连接失败',
    fieldErrors = [],
    requestId = null,
    retryAfterMs = null,
  }) {
    super(message);
    this.name = 'ApiClientError';
    this.status = status;
    this.code = code;
    this.fieldErrors = fieldErrors;
    this.requestId = requestId;
    this.retryAfterMs = retryAfterMs;
  }
}

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null;
  };
}

export async function http(path, options = {}) {
  const {
    timeoutMs = 0,
    signal: externalSignal,
    ...requestOptions
  } = options;
  const headers = new Headers(requestOptions.headers || {});
  const token = tokenStorage.get();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (
    requestOptions.body &&
    !(requestOptions.body instanceof FormData) &&
    !headers.has('Content-Type')
  ) {
    headers.set('Content-Type', 'application/json');
  }

  const controller = new AbortController();
  let timedOut = false;
  let externallyAborted = false;
  let timeoutId = null;
  const abortFromExternalSignal = () => {
    externallyAborted = true;
    controller.abort(externalSignal?.reason);
  };
  if (externalSignal?.aborted) {
    abortFromExternalSignal();
  } else {
    externalSignal?.addEventListener('abort', abortFromExternalSignal, {
      once: true,
    });
  }
  if (Number.isFinite(timeoutMs) && timeoutMs > 0) {
    timeoutId = globalThis.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
  }

  let response;
  try {
    response = await fetch(`${env.apiBaseUrl}${path}`, {
      ...requestOptions,
      headers,
      signal: controller.signal,
    });
  } catch {
    if (timedOut) {
      throw new ApiClientError({
        code: 'REQUEST_TIMEOUT',
        message: '请求等待超时',
      });
    }
    if (externallyAborted) {
      throw new ApiClientError({
        code: 'REQUEST_ABORTED',
        message: '请求已停止',
      });
    }
    throw new ApiClientError({});
  } finally {
    if (timeoutId !== null) globalThis.clearTimeout(timeoutId);
    externalSignal?.removeEventListener('abort', abortFromExternalSignal);
  }

  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw errorFromResponse(response, body);
  }
  return body;
}

export function errorFromResponse(response, body) {
  if (response.status === 401) unauthorizedHandler?.();
  return new ApiClientError({
    status: response.status,
    code: body?.code || `HTTP_${response.status}`,
    message: body?.message || '请求失败，请稍后重试',
    fieldErrors: body?.field_errors || [],
    requestId: body?.request_id || response.headers.get('X-Request-ID'),
    retryAfterMs: parseRetryAfter(response.headers.get('Retry-After')),
  });
}

function parseRetryAfter(rawValue) {
  if (!rawValue) return null;
  const seconds = Number(rawValue);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1000;
  const timestamp = Date.parse(rawValue);
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, timestamp - Date.now());
}
