# Observability baseline and telemetry contract

## Captured baseline

- Captured: 2026-08-27 (Asia/Shanghai)
- Git revision: `78f4a9e` on `feat/fusion-phase-3`
- Python: 3.14.5
- Node.js: 24.15.0
- npm: 11.12.1
- Observability: disabled by default

The existing offline verification completed successfully before the
observability changes:

| Check | Result | Duration |
| --- | --- | ---: |
| Backend unit tests | 118 passed, 4 skipped | 3.269 s |
| Frontend lint | passed | included in full suite |
| Frontend tests | 5 files and 12 tests passed | 33.49 s |
| Frontend production build | passed, 62 modules | 2.89 s |

The skipped tests require an explicitly enabled real MongoDB integration or
an explicitly authorized live LLM request. No external LLM call was made while
capturing this baseline.

The API became available on `127.0.0.1:8000` after the offline checks. It was
not started or stopped by this baseline task. Twenty sequential local requests
were sampled without a warm-up request:

| Runtime baseline | HTTP result | Mean | P50 | P95 | Maximum |
| --- | --- | ---: | ---: | ---: | ---: |
| `/health/ready` | 20/20 HTTP 200 | 7.89 ms | 7.57 ms | 9.31 ms | 15.92 ms |
| `/catalog/shops` | 20/20 HTTP 200 | 8.68 ms | 7.42 ms | 8.89 ms | 31.70 ms |

The process owning port 8000 used 35.49 MiB working set and 26.80 MiB private
memory immediately before the samples. Its cumulative CPU value did not change
at the script's three-decimal-second resolution during these forty requests.

The following live baselines remain explicitly uncollected rather than being
replaced by mock measurements:

| Runtime baseline | Status | Reason |
| --- | --- | --- |
| `/chat/stream` pure model | not collected | requires an authorized live LLM call |
| `/chat/stream` read tool | not collected | requires live data and an authorized LLM call |
| `/chat/stream` write confirmation | not collected | creates conversation/command data and may call the LLM |
| Backend conversation CPU and memory | not collected | requires an authorized live conversation |

Use `scripts/observability-baseline.ps1` after the development stack is
running. Endpoint measurements do not need credentials:

```powershell
.\scripts\observability-baseline.ps1
```

Live chat scenarios are opt-in. Supplying a token and prompt explicitly
authorizes the corresponding database writes and model calls:

```powershell
.\scripts\observability-baseline.ps1 `
  -BearerToken $token `
  -PureModelPrompt "只回复：你好" `
  -ReadToolPrompt "列出当前可用店铺" `
  -WriteConfirmationPrompt "使用测试账号和测试商品生成一张待确认订单"
```

The machine-readable result is written to
`.runtime-logs/observability-baseline.json`, which is intentionally ignored by
Git because it may describe local runtime characteristics.

## Post-change verification

After adding the opt-in configuration, contract, baseline collector and two
configuration tests, the complete project verification passed:

- Backend: 120 tests passed, 4 explicitly skipped integration tests.
- Frontend ESLint: passed.
- Frontend Vitest: 5 files and 12 tests passed.
- Frontend production build: passed, 62 modules transformed.

## Correlation contract

| Field | Owner and lifetime | Storage and indexing rule |
| --- | --- | --- |
| `trace_id` | W3C trace context for one distributed operation | Trace and correlated logs; never a metric label |
| `request_id` | One inbound HTTP request | Response header/body, root span and logs; never a metric label |
| `run_id` | One SSE Agent execution | SSE `meta`, Agent spans and logs; never a metric label |
| `conversation_id` | Persistent customer-service conversation | Trace only when needed; never a metric label |
| `interrupt_id` | One pending Agent interruption | Trace and write-command correlation; never a metric label |
| `command_id` | One durable write command | Trace and worker correlation; never a metric label |

When a write command or Agent resume continues after the originating request,
the new root span must use a span link to the persisted originating trace
context. It must not pretend to be a synchronous child after that context has
ended.

## Cardinality contract

Metric labels are limited to bounded values such as `route`, `method`,
`status_code`, `outcome`, `tool.name`, `action`, `model`, and `error.type`.
User IDs, conversation IDs, request IDs, run IDs, interrupt IDs, command IDs,
raw URLs, exception messages, prompts, and response text are forbidden as
metric labels.

## Data handling contract

Telemetry must not contain:

- Authorization headers, cookies, JWTs, API keys or signatures.
- Raw customer messages, prompts or complete model responses.
- Names, phone numbers, delivery addresses or precise coordinates.
- Complete tool arguments, MongoDB statements or document bodies.
- Redis values or idempotency keys.

Route templates, bounded tool names, model names, response status, durations,
token counts and sanitized exception class names are allowed. Any later
instrumentation must remain a no-op while `OBSERVABILITY_ENABLED=false`.

## Browser and SSE tracing

The browser SDK is independently opt-in through
`VITE_OBSERVABILITY_ENABLED`. It records document load, Fetch requests,
normalized route changes and a manual `chat.stream` span. The stream span
remains open through response headers, `meta`, first token and the terminal
`done` or `error` event; cancellation and an unterminated connection are
recorded as separate outcomes. Prompt, token and response content are never
attached to telemetry.

Production builds reject cross-origin OTLP trace endpoints. Configure the web
application to use `/telemetry/v1/traces` on its own origin and route that path
to this backend. The backend endpoint requires the current application Bearer
token, validates `Origin`, rate-limits each authenticated user in Redis,
enforces a bounded OTLP request body and forwards only JSON or protobuf traces
to the server-side `OTEL_EXPORTER_OTLP_ENDPOINT`. The Collector therefore does
not need a public browser-facing listener. Every production web origin must be
listed explicitly in `BROWSER_TELEMETRY_ALLOWED_ORIGINS`.

## Grafana dashboard and alerting

The local LGTM container provisions the repository-owned dashboard and alert
rules at startup. This keeps panel queries and thresholds reviewable in Git
instead of relying on changes made only in a developer's Grafana database.

- Dashboard: `infra/grafana/dashboards/smartserve-overview.json`
- Dashboard provider: `infra/grafana/provisioning/dashboards/smartserve.yaml`
- Alert rules: `infra/grafana/provisioning/alerting/smartserve-alerts.yaml`
- Local URL: `http://127.0.0.1:3000/d/smartserve-overview`

The overview covers HTTP traffic and latency, active SSE connections, Agent
outcomes and first-token latency, LLM calls and tokens, Tool calls, write
command confirmation/recovery, and MongoDB, Redis, DeepSeek and AMap
dependencies. The `environment` variable defaults to all environments and can
be narrowed when several deployments report to the same Prometheus instance.

The first alert group evaluates every 30 seconds:

| Alert | Condition | Sustain window |
| --- | --- | ---: |
| API error rate | 5-minute 5xx rate greater than 5% | 2 minutes |
| Agent timeout rate | 5-minute timeout rate greater than 2% | 2 minutes |
| Agent latency | 5-minute P95 greater than 30 seconds | 2 minutes |
| Tool failure rate | 5-minute failure rate greater than 5% | 2 minutes |
| Overdue write command | one or more commands exceed the execution lease | 2 minutes |
| Dependency readiness | MongoDB or Redis reports not ready | 1 minute |

Contact points and notification policies are intentionally not stored in the
development provisioning files because mail, WeCom and DingTalk credentials
are environment-specific secrets. Configure a contact point in Grafana (or a
separate deployment-secret provisioning file), then route alerts labelled
`service=smartserve` to it. The rules themselves can be tested without a
contact point: a sustained failing metric first enters `Pending`, then
`Firing`, and returns to `Normal` after recovery.

The live cross-signal acceptance procedure is documented in
[`observability-acceptance.md`](observability-acceptance.md). It covers the
browser-to-Agent trace, request-ID log lookup, failure injection, Worker Span
Links, sensitive-data scanning, disabled mode and P95 overhead comparison.
