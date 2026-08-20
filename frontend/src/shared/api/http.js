import { env } from '../config/env.js';
import { tokenStorage } from '../storage/tokenStorage.js';

let unauthorizedHandler = null;

export class ApiClientError extends Error {
  constructor({ status = 0, code = 'NETWORK_ERROR', message = '网络连接失败', fieldErrors = [], requestId = null }) {
    super(message);
    this.name = 'ApiClientError';
    this.status = status;
    this.code = code;
    this.fieldErrors = fieldErrors;
    this.requestId = requestId;
  }
}

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
  return () => {
    if (unauthorizedHandler === handler) unauthorizedHandler = null;
  };
}

export async function http(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = tokenStorage.get();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  let response;
  try {
    response = await fetch(`${env.apiBaseUrl}${path}`, { ...options, headers });
  } catch {
    throw new ApiClientError({});
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
  });
}
