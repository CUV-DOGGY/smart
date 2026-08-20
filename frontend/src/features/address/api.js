import { http } from '../../shared/api/http.js';

export const addressApi = {
  list: () => http('/addresses'),
  create: (payload) => http('/addresses', { method: 'POST', body: JSON.stringify(payload) }),
  update: (id, payload) => http(`/addresses/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  setDefault: (id) => http(`/addresses/${id}/set-default`, { method: 'POST' }),
  remove: (id) => http(`/addresses/${id}`, { method: 'DELETE' }),
};
