import { trace } from '@opentelemetry/api';
import { ZoneContextManager } from '@opentelemetry/context-zone';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { registerInstrumentations } from '@opentelemetry/instrumentation';
import { DocumentLoadInstrumentation } from '@opentelemetry/instrumentation-document-load';
import { FetchInstrumentation } from '@opentelemetry/instrumentation-fetch';
import { resourceFromAttributes } from '@opentelemetry/resources';
import {
  BatchSpanProcessor,
  ParentBasedSampler,
  TraceIdRatioBasedSampler,
  WebTracerProvider,
} from '@opentelemetry/sdk-trace-web';

import { env } from '../config/env.js';
import { tokenStorage } from '../storage/tokenStorage.js';

const INSTRUMENTATION_NAME = 'smartserve.web';
let initialized = false;
let lastRoute = null;

export function initializeBrowserObservability() {
  if (initialized || !env.observabilityEnabled || typeof window === 'undefined') {
    return initialized;
  }

  try {
    const traceEndpoint = resolveTraceEndpoint();
    const exporter = new OTLPTraceExporter({
      url: traceEndpoint.href,
      headers: async () => {
        const token = tokenStorage.get();
        return token ? { Authorization: `Bearer ${token}` } : {};
      },
    });
    const provider = new WebTracerProvider({
      resource: resourceFromAttributes({
        'service.name': env.otelServiceName,
        'deployment.environment.name': env.otelEnvironment,
      }),
      sampler: new ParentBasedSampler({
        root: new TraceIdRatioBasedSampler(env.otelTraceSampleRatio),
      }),
      spanProcessors: [new BatchSpanProcessor(exporter)],
    });

    provider.register({ contextManager: new ZoneContextManager() });
    registerInstrumentations({
      tracerProvider: provider,
      instrumentations: [
        new DocumentLoadInstrumentation(),
        new FetchInstrumentation({
          ignoreUrls: [traceEndpoint.href],
          propagateTraceHeaderCorsUrls: [apiUrlPattern(env.apiBaseUrl)],
        }),
      ],
    });
    initialized = true;
  } catch (error) {
    // Telemetry is best-effort and must never prevent the application boot.
    console.warn('浏览器追踪初始化失败', error);
  }
  return initialized;
}

export function traceRouteChange(pathname) {
  const route = normalizeRoute(pathname);
  if (!initialized || route === lastRoute) return;

  const previousRoute = lastRoute;
  lastRoute = route;
  trace.getTracer(INSTRUMENTATION_NAME).startActiveSpan(
    'navigation.route',
    {
      attributes: {
        'url.path': route,
        ...(previousRoute ? { 'navigation.from': previousRoute } : {}),
      },
    },
    (span) => {
      span.addEvent('navigation.route.changed');
      span.end();
    },
  );
}

function resolveTraceEndpoint() {
  const endpoint = new URL(env.otelTraceEndpoint, window.location.origin);
  if (import.meta.env.PROD && endpoint.origin !== window.location.origin) {
    throw new Error('生产环境只允许使用同源浏览器遥测入口');
  }
  return endpoint;
}

function apiUrlPattern(apiBaseUrl) {
  const escaped = apiBaseUrl.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`^${escaped}(?:/|$)`);
}

function normalizeRoute(pathname) {
  const route = pathname || '/';
  return route
    .split('/')
    .map((part) =>
      /^\d+$|^[0-9a-f]{24}$|^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(part)
        ? ':id'
        : part,
    )
    .join('/');
}
