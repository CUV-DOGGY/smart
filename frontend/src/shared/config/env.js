export const env = Object.freeze({
  apiBaseUrl: (
    import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
  ).replace(/\/$/, ''),
  orderCreateTimeoutMs: parsePositiveInteger(
    import.meta.env.VITE_ORDER_CREATE_TIMEOUT_MS,
    8000,
  ),
  orderAttemptQueryTimeoutMs: parsePositiveInteger(
    import.meta.env.VITE_ORDER_ATTEMPT_QUERY_TIMEOUT_MS,
    3000,
  ),
  amapKey: import.meta.env.VITE_AMAP_JS_KEY?.trim() || '',
  amapSecurityCode: import.meta.env.VITE_AMAP_SECURITY_JS_CODE?.trim() || '',
  observabilityEnabled:
    import.meta.env.VITE_OBSERVABILITY_ENABLED?.toLowerCase() === 'true',
  otelTraceEndpoint:
    import.meta.env.VITE_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT?.trim() ||
    '/telemetry/v1/traces',
  otelServiceName:
    import.meta.env.VITE_OTEL_SERVICE_NAME?.trim() || 'smartserve-web',
  otelEnvironment:
    import.meta.env.VITE_OTEL_ENVIRONMENT?.trim() || import.meta.env.MODE,
  otelTraceSampleRatio: parseSampleRatio(
    import.meta.env.VITE_OTEL_TRACE_SAMPLE_RATIO,
  ),
});

function parseSampleRatio(rawValue) {
  const value = Number(rawValue ?? 1);
  return Number.isFinite(value) && value >= 0 && value <= 1 ? value : 1;
}

function parsePositiveInteger(rawValue, fallback) {
  const value = Number(rawValue);
  return Number.isInteger(value) && value > 0 ? value : fallback;
}
