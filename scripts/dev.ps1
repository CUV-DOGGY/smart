[CmdletBinding()]
param(
    [int]$Port = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$frontendRoot = Join-Path $repoRoot "frontend"
$pythonPath = Join-Path $backendRoot ".venv\Scripts\python.exe"
$composeFile = Join-Path $repoRoot "infra\compose.dev.yml"
$runtimeLogRoot = Join-Path $repoRoot ".runtime-logs"
$localMongoUrl = "mongodb://localhost:27017/?replicaSet=rs0"
$localRedisUrl = "redis://127.0.0.1:6380/0"
$localOtlpEndpoint = "http://127.0.0.1:4318"
$previousMongoUrl = [Environment]::GetEnvironmentVariable("MONGODB_URL", "Process")
$previousRedisUrl = [Environment]::GetEnvironmentVariable("REDIS_URL", "Process")
$previousApiUrl = [Environment]::GetEnvironmentVariable("VITE_API_BASE_URL", "Process")
$observabilityEnvironmentNames = @(
    "OBSERVABILITY_ENABLED",
    "OTEL_SERVICE_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_ENVIRONMENT",
    "OTEL_TRACE_SAMPLE_RATIO",
    "OTEL_METRIC_EXPORT_INTERVAL",
    "BROWSER_TELEMETRY_ENABLED",
    "VITE_OBSERVABILITY_ENABLED",
    "VITE_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "VITE_OTEL_SERVICE_NAME",
    "VITE_OTEL_ENVIRONMENT",
    "VITE_OTEL_TRACE_SAMPLE_RATIO"
)
$previousObservabilityEnvironment = @{}
foreach ($name in $observabilityEnvironmentNames) {
    $previousObservabilityEnvironment[$name] = [Environment]::GetEnvironmentVariable(
        $name,
        "Process"
    )
}
$backendProcess = $null
$taskkillPath = Join-Path $env:SystemRoot "System32\taskkill.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Virtual environment is missing. Run scripts/bootstrap.ps1 first."
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "node_modules"))) {
    throw "Frontend dependencies are missing. Run scripts/bootstrap.ps1 first."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is not available on PATH."
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCommand) {
    $dockerPath = $dockerCommand.Source
} else {
    $dockerPath = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"
}
if (-not (Test-Path -LiteralPath $dockerPath)) {
    throw "Docker CLI is unavailable. Install and start Docker Desktop first."
}

& $dockerPath info *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not running." }
& $dockerPath compose -f $composeFile up -d --wait redis observability
if ($LASTEXITCODE -ne 0) {
    throw "Redis or the local observability stack failed to start."
}

$readinessCode = @"
from pymongo import MongoClient
from redis import Redis

mongo = MongoClient('$localMongoUrl', serverSelectionTimeoutMS=2000)
redis = Redis.from_url('$localRedisUrl', socket_connect_timeout=2)
try:
    assert mongo.admin.command('ping')['ok'] == 1
    assert redis.ping()
    print('MongoDB and Redis are ready')
finally:
    redis.close()
    mongo.close()
"@
& $pythonPath -c $readinessCode
if ($LASTEXITCODE -ne 0) { throw "MongoDB or Redis readiness check failed." }

$portOwners = @(
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)
if ($portOwners.Count -gt 0) {
    $ownerText = $portOwners -join ", "
    throw "Backend port $Port is already in use by PID(s): $ownerText. Stop the previous development process first."
}

New-Item -ItemType Directory -Force -Path $runtimeLogRoot | Out-Null
$stdoutLog = Join-Path $runtimeLogRoot "backend.stdout.log"
$stderrLog = Join-Path $runtimeLogRoot "backend.stderr.log"

try {
    $env:MONGODB_URL = $localMongoUrl
    $env:REDIS_URL = $localRedisUrl
    $env:VITE_API_BASE_URL = "http://127.0.0.1:$Port"
    $env:OBSERVABILITY_ENABLED = "true"
    $env:OTEL_SERVICE_NAME = "smartserve-backend"
    $env:OTEL_EXPORTER_OTLP_ENDPOINT = $localOtlpEndpoint
    $env:OTEL_ENVIRONMENT = "development"
    $env:OTEL_TRACE_SAMPLE_RATIO = "1.0"
    $env:OTEL_METRIC_EXPORT_INTERVAL = "10000"
    $env:BROWSER_TELEMETRY_ENABLED = "true"
    $env:VITE_OBSERVABILITY_ENABLED = "true"
    $env:VITE_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = "/telemetry/v1/traces"
    $env:VITE_OTEL_SERVICE_NAME = "smartserve-web"
    $env:VITE_OTEL_ENVIRONMENT = "development"
    $env:VITE_OTEL_TRACE_SAMPLE_RATIO = "1.0"
    $backendProcess = Start-Process -FilePath $pythonPath `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port", "--reload") `
        -WorkingDirectory $backendRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -WindowStyle Hidden `
        -PassThru

    $backendReady = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($backendProcess.HasExited) {
            throw "Backend exited during startup. See $stderrLog"
        }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/live" -TimeoutSec 1
            if ($health.status -eq "ok") {
                $backendReady = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $backendReady) {
        throw "Backend did not become ready. See $stderrLog"
    }

    Write-Host "Backend: http://127.0.0.1:$Port/docs"
    Write-Host "Frontend: http://127.0.0.1:$FrontendPort"
    Write-Host "Grafana: http://127.0.0.1:3000 (admin/admin)"
    Push-Location $frontendRoot
    try {
        & npm run dev -- --host 127.0.0.1 --port $FrontendPort
        if ($LASTEXITCODE -ne 0) { throw "Frontend development server failed." }
    } finally {
        Pop-Location
    }
} finally {
    if ($backendProcess -and -not $backendProcess.HasExited) {
        & $taskkillPath /PID $backendProcess.Id /T /F *> $null
    }
    [Environment]::SetEnvironmentVariable("MONGODB_URL", $previousMongoUrl, "Process")
    [Environment]::SetEnvironmentVariable("REDIS_URL", $previousRedisUrl, "Process")
    [Environment]::SetEnvironmentVariable("VITE_API_BASE_URL", $previousApiUrl, "Process")
    foreach ($name in $observabilityEnvironmentNames) {
        $previousValue = $previousObservabilityEnvironment[$name]
        if ($null -eq $previousValue) {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
        } else {
            [Environment]::SetEnvironmentVariable($name, $previousValue, "Process")
        }
    }
}
