import { describe, expect, it, vi } from 'vitest';

import { createOrderWithRetry } from './orderRetry.js';

const PAYLOAD = {
  shop_id: 'shop-001',
  address_id: 'address-001',
  items: [{ food_id: 'food-001', quantity: 1 }],
};
const KEY = 'web-checkout-001';
const TEST_OPTIONS = {
  createTimeoutMs: 10,
  queryTimeoutMs: 10,
  maxCreateAttempts: 3,
  retryBackoffsMs: [1, 2],
  confirmationDelaysMs: [1, 2, 3],
  jitterMs: 0,
  totalBudgetMs: 10000,
};

function makeApi() {
  return {
    create: vi.fn(),
    findByIdempotencyKey: vi.fn(),
  };
}

describe('createOrderWithRetry', () => {
  it('returns a recovered order before sending a duplicate POST', async () => {
    const api = makeApi();
    api.create.mockRejectedValue({ code: 'REQUEST_TIMEOUT', status: 0 });
    api.findByIdempotencyKey.mockResolvedValue({
      status: 'succeeded',
      order: { order_id: 'order-001' },
    });

    const result = await createOrderWithRetry({
      payload: PAYLOAD,
      idempotencyKey: KEY,
      api,
      sleep: vi.fn(),
      options: TEST_OPTIONS,
    });

    expect(result).toEqual({
      status: 'succeeded',
      order: { order_id: 'order-001' },
    });
    expect(api.create).toHaveBeenCalledOnce();
  });

  it('retries a missing request with the same idempotency key', async () => {
    const api = makeApi();
    api.create
      .mockRejectedValueOnce({ code: 'NETWORK_ERROR', status: 0 })
      .mockResolvedValueOnce({ order_id: 'order-001' });
    api.findByIdempotencyKey.mockResolvedValue({ status: 'not_found' });
    const sleep = vi.fn();

    const result = await createOrderWithRetry({
      payload: PAYLOAD,
      idempotencyKey: KEY,
      api,
      sleep,
      options: TEST_OPTIONS,
    });

    expect(result.status).toBe('succeeded');
    expect(api.create).toHaveBeenCalledTimes(2);
    expect(api.create.mock.calls[0][1]).toBe(KEY);
    expect(api.create.mock.calls[1][1]).toBe(KEY);
    expect(sleep).toHaveBeenCalledWith(1);
  });

  it('does not retry a definitive business error', async () => {
    const api = makeApi();
    const error = {
      status: 409,
      code: 'INSUFFICIENT_STOCK',
      message: '库存不足',
    };
    api.create.mockRejectedValue(error);

    const result = await createOrderWithRetry({
      payload: PAYLOAD,
      idempotencyKey: KEY,
      api,
      sleep: vi.fn(),
      options: TEST_OPTIONS,
    });

    expect(result).toEqual({ status: 'failed', error });
    expect(api.findByIdempotencyKey).not.toHaveBeenCalled();
  });

  it('stops after the bounded confirmation budget', async () => {
    const api = makeApi();
    api.create.mockRejectedValue({ code: 'REQUEST_TIMEOUT', status: 0 });
    api.findByIdempotencyKey.mockResolvedValue({ status: 'processing' });
    const sleep = vi.fn();

    const result = await createOrderWithRetry({
      payload: PAYLOAD,
      idempotencyKey: KEY,
      api,
      sleep,
      options: TEST_OPTIONS,
    });

    expect(result.status).toBe('unknown');
    expect(api.create).toHaveBeenCalledOnce();
    expect(api.findByIdempotencyKey).toHaveBeenCalledTimes(4);
    expect(sleep).toHaveBeenCalledTimes(3);
  });
});
