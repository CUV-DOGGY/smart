[CmdletBinding()]
param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$pythonPath = Join-Path $backendRoot ".venv\Scripts\python.exe"
$composeFile = Join-Path $repoRoot "infra\compose.dev.yml"
$localMongoUrl = "mongodb://localhost:27017/?replicaSet=rs0"
$localRedisUrl = "redis://127.0.0.1:6380/0"
$previousMongoUrl = [Environment]::GetEnvironmentVariable("MONGODB_URL", "Process")
$previousRedisUrl = [Environment]::GetEnvironmentVariable("REDIS_URL", "Process")

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Virtual environment is missing. Run scripts/bootstrap.ps1 first."
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
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not running."
}

& $dockerPath compose -f $composeFile up -d --wait redis
if ($LASTEXITCODE -ne 0) {
    throw "Redis failed to start."
}

& $pythonPath -c "from pymongo import MongoClient; from redis import Redis; m=MongoClient('$localMongoUrl', serverSelectionTimeoutMS=2000); assert m.admin.command('ping')['ok'] == 1; assert Redis.from_url('$localRedisUrl', socket_connect_timeout=2).ping(); print('MongoDB and Redis are ready')"
if ($LASTEXITCODE -ne 0) {
    throw "MongoDB or Redis readiness check failed."
}

Push-Location $backendRoot
try {
    $env:MONGODB_URL = $localMongoUrl
    $env:REDIS_URL = $localRedisUrl
    & $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port $Port --reload
} finally {
    [Environment]::SetEnvironmentVariable("MONGODB_URL", $previousMongoUrl, "Process")
    [Environment]::SetEnvironmentVariable("REDIS_URL", $previousRedisUrl, "Process")
    Pop-Location
}
