import { http } from '../../shared/api/http.js';

export const orderApi = {
  listShops: (options = {}) => http('/catalog/shops', options),
  getShop: (shopId, options = {}) =>
    http(`/catalog/shops/${encodeURIComponent(shopId)}`, options),
  listProducts: (shopId, options = {}) =>
    http(
      `/catalog/shops/${encodeURIComponent(shopId)}/products`,
      options,
    ),
  list: (options = {}) => http('/orders', options),
  get: (orderId) => http(`/orders/${encodeURIComponent(orderId)}`),
  findByIdempotencyKey: (idempotencyKey, options = {}) =>
    http('/orders/by-idempotency-key', {
      ...options,
      headers: { 'Idempotency-Key': idempotencyKey },
      cache: 'no-store',
    }),
  create: (payload, idempotencyKey, options = {}) =>
    http('/orders', {
      ...options,
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(payload),
    }),
  cancel: (orderId) =>
    http(`/orders/${encodeURIComponent(orderId)}/cancel`, { method: 'POST' }),
};
