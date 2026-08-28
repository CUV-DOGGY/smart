# Observability end-to-end acceptance

This acceptance is intentionally separate from the offline unit suite. It
uses a real local MongoDB replica set, Redis, Grafana LGTM and the configured
DeepSeek account. It creates an isolated user, shop, product, address, orders,
conversations and write commands whose identifiers start with `obs-` or
`e2e-`.

## Prerequisites

Start the normal development stack with observability enabled:

```powershell
.\scripts\dev.ps1
```

The acceptance runner expects the API at `http://127.0.0.1:8000` and Grafana
at `http://127.0.0.1:3000`. Override the corresponding command-line options
when using other local ports. The script never writes credentials, prompt
text, token text, model responses, addresses or phone numbers to its report.

## Business and telemetry acceptance

Use a unique alphanumeric run identifier. Keep the test password out of the
command line so it is not visible in the process list:

```powershell
$env:OBSERVABILITY_E2E_PASSWORD = Read-Host "Temporary E2E password"
.\backend\.venv\Scripts\python.exe `
  .\scripts\observability-e2e.py `
  --run-id 20260827a `
  --username obs_e2e_20260827a
```

The runner verifies login and list endpoints, a pure-model response, a
read-only Tool call, rejected and approved order confirmations, client-side
SSE disconnection, Worker recovery, Tempo span structure, Loki request-ID
correlation, recovery Span Links and the sensitive-data contract. Results are
written to `.runtime-logs/observability-e2e.json`.

For the browser portion, sign in to the local frontend using the same temporary
account and send a product-list request for the generated `obs-shop-<run-id>`.
After the response finishes and the browser exporter has flushed, validate the
complete browser trace without rerunning business mutations:

```powershell
.\backend\.venv\Scripts\python.exe `
  .\scripts\observability-e2e.py `
  --run-id 20260827a `
  --username obs_e2e_20260827a `
  --skip-business `
  --skip-traces `
  --validate-browser-trace
```

The selected trace must contain `chat.stream`, `POST /chat/stream`,
`agent.run`, `agent.graph`, `agent.model`, `agent.tool.list_products`, MongoDB
spans and Redis spans in one trace.

## Isolated dependency faults

Do not stop shared database services merely to test readiness. Start the
included TCP proxies and point a separate backend instance at ports 27018 and
6381:

```powershell
.\backend\.venv\Scripts\python.exe .\scripts\tcp-fault-proxy.py `
  --listen-port 27018 --target-port 27017
.\backend\.venv\Scripts\python.exe .\scripts\tcp-fault-proxy.py `
  --listen-port 6381 --target-port 6380
```

Use `mongodb://127.0.0.1:27018/?directConnection=true` and
`redis://127.0.0.1:6381/0` for that backend. Terminating one proxy must make
`/health/ready` return 503; restarting it must restore HTTP 200. Pass the two
failure request IDs back to the acceptance runner using
`--mongodb-failure-request-id` and `--redis-failure-request-id` so the failure
traces are added to the report.

## Disabled mode and performance

Start a second backend with `OBSERVABILITY_ENABLED=false`, then pass its URL as
`--disabled-api-base-url`. The runner checks readiness and compares P95 against
the enabled process. The default run uses 80 iterations; increase it with
`--performance-iterations`. The acceptance target is no more than roughly 10%
P95 overhead on the same machine and dependency set.

An invalid DeepSeek endpoint can be tested on another isolated backend and
passed as `--fault-api-base-url`; the expected SSE terminal event is `error`,
without exposing the upstream exception or credentials to the client.

## Cleanup

After browser validation, rerun with `--skip-business --skip-traces --cleanup`.
Cleanup targets only the exact acceptance user and its associated records plus
the generated shop and product. Stop the temporary backend and proxy processes
afterward; the normal development services can remain running.
