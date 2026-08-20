export const env = Object.freeze({
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, ''),
  amapKey: import.meta.env.VITE_AMAP_JS_KEY?.trim() || '',
  amapSecurityCode: import.meta.env.VITE_AMAP_SECURITY_JS_CODE?.trim() || '',
});
