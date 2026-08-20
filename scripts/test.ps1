[CmdletBinding()]
param(
    [switch]$Integration
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$uvCache = Join-Path $repoRoot "backend\.uv-cache"
$integrationEnvironmentNames = @(
    "RUN_MONGO_INTEGRATION",
    "TEST_MONGODB_URL",
    "TEST_MONGODB_DB_NAME"
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
        & uv run --project backend --locked --cache-dir $uvCache python -m unittest discover -s backend\tests -t backend -p test_order_repository_mongo_integration.py -v
        if ($LASTEXITCODE -ne 0) {
            throw "MongoDB integration tests failed."
        }
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
