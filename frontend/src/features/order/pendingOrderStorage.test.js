import { afterEach, describe, expect, it } from 'vitest';

import { pendingOrderStorage } from './pendingOrderStorage.js';

const ATTEMPT = {
  fingerprint: '{"shop_id":"shop-001"}',
  key: 'web-checkout-001',
  createdAt: '2026-08-28T00:00:00.000Z',
  payload: {
    shop_id: 'shop-001',
    address_id: 'address-001',
    items: [{ food_id: 'food-001', quantity: 1 }],
  },
};

afterEach(() => localStorage.clear());

describe('pendingOrderStorage', () => {
  it('persists a pending attempt for the same user across page reloads', () => {
    expect(pendingOrderStorage.set('user-001', ATTEMPT)).toBe(true);

    expect(pendingOrderStorage.get('user-001')).toEqual(ATTEMPT);
    expect(pendingOrderStorage.get('user-002')).toBeNull();
  });

  it('only clears the attempt that produced the confirmed result', () => {
    pendingOrderStorage.set('user-001', ATTEMPT);

    expect(pendingOrderStorage.clear('user-001', 'another-key')).toBe(false);
    expect(pendingOrderStorage.get('user-001')).toEqual(ATTEMPT);
    expect(pendingOrderStorage.clear('user-001', ATTEMPT.key)).toBe(true);
    expect(pendingOrderStorage.get('user-001')).toBeNull();
  });
});
