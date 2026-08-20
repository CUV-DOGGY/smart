import { http } from '../../shared/api/http.js';

export const authApi = {
  register(payload) {
    return http('/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  login(username, password) {
    const body = new URLSearchParams({ username, password });
    return http('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
  },
  me() {
    return http('/auth/me');
  },
};
