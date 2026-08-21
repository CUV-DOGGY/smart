import { http } from '../../shared/api/http.js';

export const orderApi = {
  listShops: () => http('/catalog/shops'),
  listProducts: (shopId) =>
    http(`/catalog/shops/${encodeURIComponent(shopId)}/products`),
  list: () => http('/orders'),
  get: (orderId) => http(`/orders/${encodeURIComponent(orderId)}`),
  create: (payload, idempotencyKey) =>
    http('/orders', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(payload),
    }),
  cancel: (orderId) =>
    http(`/orders/${encodeURIComponent(orderId)}/cancel`, { method: 'POST' }),
};
