import { env } from '../../shared/config/env.js';
import { orderApi } from './api.js';

export const ORDER_RETRY_DEFAULTS = Object.freeze({
  createTimeoutMs: env.orderCreateTimeoutMs,
  queryTimeoutMs: env.orderAttemptQueryTimeoutMs,
  maxCreateAttempts: 3,
  retryBackoffsMs: [500, 1500],
  confirmationDelaysMs: [2000, 5000, 10000],
  jitterMs: 250,
  totalBudgetMs: 30000,
});

const RETRYABLE_HTTP_STATUSES = new Set([408, 429, 500, 502, 503, 504]);
const AMBIGUOUS_ERROR_CODES = new Set([
  'NETWORK_ERROR',
  'REQUEST_TIMEOUT',
  'REQUEST_ABORTED',
  'IDEMPOTENCY_KEY_CONFLICT',
]);

export async function createOrderWithRetry({
  payload,
  idempotencyKey,
  onProgress = () => {},
  api = orderApi,
  sleep = wait,
  random = Math.random,
  options = {},
  deadlineAt = null,
}) {
  const policy = { ...ORDER_RETRY_DEFAULTS, ...options };
  const deadline = deadlineAt || Date.now() + policy.totalBudgetMs;
  let lastError = null;

  for (let attempt = 1; attempt <= policy.maxCreateAttempts; attempt += 1) {
    const createTimeoutMs = timeoutWithinBudget(
      policy.createTimeoutMs,
      deadline,
    );
    if (createTimeoutMs <= 0) return { status: 'unknown', error: lastError };
    onProgress({
      phase: 'submitting',
      attempt,
      total: policy.maxCreateAttempts,
    });
    try {
      const order = await api.create(payload, idempotencyKey, {
        timeoutMs: createTimeoutMs,
      });
      return { status: 'succeeded', order };
    } catch (error) {
      lastError = error;
      const terminal = terminalOutcomeFromError(error);
      if (terminal) return terminal;
      if (!isAmbiguousCreateError(error)) {
        return { status: 'failed', error };
      }

      onProgress({ phase: 'confirming', attempt });
      const queryResult = await queryAttempt(
        api,
        idempotencyKey,
        policy,
        deadline,
      );
      const queryOutcome = terminalOutcomeFromAttempt(queryResult.attempt);
      if (queryOutcome) return queryOutcome;
      if (isProcessing(queryResult.attempt)) {
        return confirmUntilBudget({
          api,
          idempotencyKey,
          onProgress,
          policy,
          sleep,
          lastError,
          deadline,
        });
      }

      if (attempt < policy.maxCreateAttempts) {
        const retryDelay = retryDelayMs(
          policy,
          attempt,
          error?.retryAfterMs,
          random,
        );
        onProgress({
          phase: 'retry_wait',
          attempt: attempt + 1,
          total: policy.maxCreateAttempts,
          delayMs: retryDelay,
        });
        if (Date.now() + retryDelay >= deadline) {
          return { status: 'unknown', error: lastError };
        }
        await sleep(retryDelay);
      }
    }
  }

  return confirmUntilBudget({
    api,
    idempotencyKey,
    onProgress,
    policy,
    sleep,
    lastError,
    deadline,
  });
}

export async function resumeOrderAttempt({
  payload,
  idempotencyKey,
  onProgress = () => {},
  api = orderApi,
  sleep = wait,
  random = Math.random,
  options = {},
}) {
  const policy = { ...ORDER_RETRY_DEFAULTS, ...options };
  const deadline = Date.now() + policy.totalBudgetMs;
  onProgress({ phase: 'confirming', attempt: 0 });
  const queryResult = await queryAttempt(
    api,
    idempotencyKey,
    policy,
    deadline,
  );
  const queryOutcome = terminalOutcomeFromAttempt(queryResult.attempt);
  if (queryOutcome) return queryOutcome;
  if (isProcessing(queryResult.attempt)) {
    return confirmUntilBudget({
      api,
      idempotencyKey,
      onProgress,
      policy,
      sleep,
      lastError: queryResult.error,
      deadline,
    });
  }
  return createOrderWithRetry({
    payload,
    idempotencyKey,
    onProgress,
    api,
    sleep,
    random,
    options: policy,
    deadlineAt: deadline,
  });
}

export async function queryOrderAttemptOnce({
  idempotencyKey,
  api = orderApi,
  queryTimeoutMs = ORDER_RETRY_DEFAULTS.queryTimeoutMs,
}) {
  return queryAttempt(api, idempotencyKey, { queryTimeoutMs }, null);
}

async function confirmUntilBudget({
  api,
  idempotencyKey,
  onProgress,
  policy,
  sleep,
  lastError,
  deadline,
}) {
  for (
    let index = 0;
    index < policy.confirmationDelaysMs.length;
    index += 1
  ) {
    if (Date.now() + policy.confirmationDelaysMs[index] >= deadline) {
      return { status: 'unknown', error: lastError };
    }
    await sleep(policy.confirmationDelaysMs[index]);
    onProgress({
      phase: 'final_confirming',
      attempt: index + 1,
      total: policy.confirmationDelaysMs.length,
    });
    const queryResult = await queryAttempt(
      api,
      idempotencyKey,
      policy,
      deadline,
    );
    if (queryResult.error) lastError = queryResult.error;
    const outcome = terminalOutcomeFromAttempt(queryResult.attempt);
    if (outcome) return outcome;
  }
  return { status: 'unknown', error: lastError };
}

async function queryAttempt(api, idempotencyKey, policy, deadline) {
  const queryTimeoutMs = timeoutWithinBudget(
    policy.queryTimeoutMs,
    deadline,
  );
  if (queryTimeoutMs <= 0) {
    return { attempt: null, error: null };
  }
  try {
    const attempt = await api.findByIdempotencyKey(idempotencyKey, {
      timeoutMs: queryTimeoutMs,
    });
    return { attempt, error: null };
  } catch (error) {
    return { attempt: null, error };
  }
}

function timeoutWithinBudget(configuredTimeoutMs, deadline) {
  if (!deadline) return configuredTimeoutMs;
  return Math.max(0, Math.min(configuredTimeoutMs, deadline - Date.now()));
}

function terminalOutcomeFromAttempt(attempt) {
  if (attempt?.status === 'succeeded' && attempt.order) {
    return { status: 'succeeded', order: attempt.order };
  }
  if (attempt?.status === 'failed') {
    return {
      status: 'failed',
      failureCode: attempt.failure_code || 'ORDER_ATTEMPT_FAILED',
    };
  }
  if (attempt?.status === 'expired') return { status: 'expired' };
  return null;
}

function terminalOutcomeFromError(error) {
  if (error?.code === 'ORDER_ATTEMPT_EXPIRED') return { status: 'expired' };
  return null;
}

function isProcessing(attempt) {
  return attempt?.status === 'received' || attempt?.status === 'processing';
}

function isAmbiguousCreateError(error) {
  return (
    AMBIGUOUS_ERROR_CODES.has(error?.code) ||
    RETRYABLE_HTTP_STATUSES.has(error?.status)
  );
}

function retryDelayMs(policy, attempt, retryAfterMs, random) {
  const configured =
    policy.retryBackoffsMs[Math.min(attempt - 1, policy.retryBackoffsMs.length - 1)] ||
    0;
  const serverDelay = Number.isFinite(retryAfterMs) ? retryAfterMs : 0;
  return (
    Math.max(configured, serverDelay) +
    Math.floor(random() * policy.jitterMs)
  );
}

function wait(delayMs) {
  return new Promise((resolve) => globalThis.setTimeout(resolve, delayMs));
}
