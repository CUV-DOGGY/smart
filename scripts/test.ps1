[CmdletBinding()]
param(
    [switch]$Integration,
    [switch]$LlmIntegration
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$uvCache = Join-Path $repoRoot "backend\.uv-cache"
$frontendRoot = Join-Path $repoRoot "frontend"
$integrationEnvironmentNames = @(
    "RUN_MONGO_INTEGRATION",
    "TEST_MONGODB_URL",
    "TEST_MONGODB_DB_NAME",
    "RUN_LLM_INTEGRATION",
    "MODEL_NAME"
)
$previousIntegrationEnvironment = @{}
foreach ($name in $integrationEnvironmentNames) {
    $previousIntegrationEnvironment[$name] = [Environment]::GetEnvironmentVariable(
        $name,
        "Process"
    )
}

Push-Location $repoRoot
try {
    & uv run --project backend --locked --cache-dir $uvCache python -m unittest discover -s backend\tests -t backend -v
    if ($LASTEXITCODE -ne 0) {
        throw "Unit tests failed."
    }

    if ($Integration) {
        $env:RUN_MONGO_INTEGRATION = "1"
        $env:TEST_MONGODB_URL = "mongodb://localhost:27017/?replicaSet=rs0"
        $env:TEST_MONGODB_DB_NAME = "smart_customer_service_integration_test"
        & uv run --project backend --locked --cache-dir $uvCache python -m unittest discover -s backend\tests -t backend -p "test_*_mongo_integration.py" -v
        if ($LASTEXITCODE -ne 0) {
            throw "MongoDB integration tests failed."
        }
    }

    if ($LlmIntegration) {
        $env:RUN_LLM_INTEGRATION = "1"
        $env:MODEL_NAME = "deepseek-v4-flash"
        & uv run --project backend --locked --cache-dir $uvCache python -m unittest discover -s backend\tests -t backend -p "test_llm_integration.py" -v
        if ($LASTEXITCODE -ne 0) {
            throw "Read-only LLM integration test failed."
        }
    }

    Push-Location $frontendRoot
    try {
        & npm run lint
        if ($LASTEXITCODE -ne 0) { throw "Frontend lint failed." }
        & npm test
        if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed." }
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
    } finally {
        Pop-Location
    }
} finally {
    foreach ($name in $integrationEnvironmentNames) {
        $previousValue = $previousIntegrationEnvironment[$name]
        if ($null -eq $previousValue) {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
        } else {
            [Environment]::SetEnvironmentVariable($name, $previousValue, "Process")
        }
    }
    Pop-Location
}
