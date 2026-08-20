[CmdletBinding()]
param(
    [string]$PythonPath = "E:\python312\python.exe"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repoRoot "backend"
$uvCache = Join-Path $backendRoot ".uv-cache"
$envExample = Join-Path $backendRoot ".env.example"
$envFile = Join-Path $backendRoot ".env"
$frontendRoot = Join-Path $repoRoot "frontend"
$frontendEnvExample = Join-Path $frontendRoot ".env.example"
$frontendEnvFile = Join-Path $frontendRoot ".env.local"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python executable not found: $PythonPath"
}

$pythonVersion = & $PythonPath -c "import platform; print(platform.python_version())"
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne "3.14.5") {
    throw "Python 3.14.5 is required; found: $pythonVersion"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not available on PATH"
}

$nodeVersion = & node --version
if ($LASTEXITCODE -ne 0 -or $nodeVersion -ne "v24.15.0") {
    throw "Node.js 24.15.0 is required; found: $nodeVersion"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm is not available on PATH"
}

Push-Location $repoRoot
try {
    & uv sync --project backend --python $PythonPath --locked --cache-dir $uvCache
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed"
    }

    if (-not (Test-Path -LiteralPath $envFile)) {
        Copy-Item -LiteralPath $envExample -Destination $envFile
        Write-Host "Created backend/.env from the example; replace placeholder secrets before startup."
    }


    Push-Location $frontendRoot
    try {
        & npm ci --cache .npm-cache --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci failed"
        }
        if (-not (Test-Path -LiteralPath $frontendEnvFile)) {
            Copy-Item -LiteralPath $frontendEnvExample -Destination $frontendEnvFile
            Write-Host "Created frontend/.env.local; configure the AMap JSAPI credentials before map testing."
        }
    } finally {
        Pop-Location
    }
} finally {
    Pop-Location
}

Write-Host "Development environment is ready with Python $pythonVersion and Node.js $nodeVersion."
