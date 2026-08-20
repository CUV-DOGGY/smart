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
} finally {
    Pop-Location
}

Write-Host "Backend environment is ready with Python $pythonVersion."
