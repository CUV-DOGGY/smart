[CmdletBinding()]
param(
    [string]$ApiBaseUrl = "http://127.0.0.1:8000",
    [ValidateRange(1, 1000)]
    [int]$Iterations = 20,
    [string]$BearerToken,
    [string]$PureModelPrompt,
    [string]$ReadToolPrompt,
    [string]$WriteConfirmationPrompt,
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeLogRoot = Join-Path $repoRoot ".runtime-logs"
if (-not $OutputPath) {
    $OutputPath = Join-Path $runtimeLogRoot "observability-baseline.json"
}

function Get-Percentile {
    param(
        [double[]]$Values,
        [ValidateRange(0, 1)]
        [double]$Percentile
    )

    if ($Values.Count -eq 0) { return $null }
    $ordered = @($Values | Sort-Object)
    $index = [Math]::Max(
        0,
        [Math]::Ceiling($Percentile * $ordered.Count) - 1
    )
    return [Math]::Round($ordered[$index], 2)
}

function Get-BackendProcessSample {
    $apiPort = ([Uri]$ApiBaseUrl).Port
    $connection = Get-NetTCPConnection `
        -LocalPort $apiPort `
        -State Listen `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
    $ownerProcessId = $connection.OwningProcess
    if (-not $ownerProcessId) {
        $listener = netstat -ano |
            Select-String "^\s*TCP\s+\S+:$apiPort\s+\S+\s+LISTENING\s+(\d+)\s*$" |
            Select-Object -First 1
        if ($listener -and $listener.Matches.Count -gt 0) {
            $ownerProcessId = [int]$listener.Matches[0].Groups[1].Value
        }
    }
    if (-not $ownerProcessId) { return $null }

    $process = Get-Process `
        -Id $ownerProcessId `
        -ErrorAction SilentlyContinue
    if (-not $process) { return $null }

    return [ordered]@{
        process_id = $process.Id
        cpu_seconds = [Math]::Round($process.CPU, 3)
        working_set_mb = [Math]::Round($process.WorkingSet64 / 1MB, 2)
        private_memory_mb = [Math]::Round($process.PrivateMemorySize64 / 1MB, 2)
    }
}

function Measure-GetEndpoint {
    param(
        [string]$Name,
        [string]$Path
    )

    $samples = [System.Collections.Generic.List[double]]::new()
    $statusCounts = @{}
    for ($index = 0; $index -lt $Iterations; $index++) {
        $stopwatch = [Diagnostics.Stopwatch]::StartNew()
        try {
            $response = Invoke-WebRequest `
                -Uri "$ApiBaseUrl$Path" `
                -Method Get `
                -TimeoutSec 30 `
                -SkipHttpErrorCheck
            $status = [string]$response.StatusCode
        } catch {
            $status = "network_error"
        } finally {
            $stopwatch.Stop()
            $samples.Add($stopwatch.Elapsed.TotalMilliseconds)
        }
        if (-not $statusCounts.ContainsKey($status)) {
            $statusCounts[$status] = 0
        }
        $statusCounts[$status]++
    }

    return [ordered]@{
        name = $Name
        path = $Path
        iterations = $Iterations
        status_counts = $statusCounts
        latency_ms = [ordered]@{
            min = [Math]::Round(($samples | Measure-Object -Minimum).Minimum, 2)
            mean = [Math]::Round(($samples | Measure-Object -Average).Average, 2)
            p50 = Get-Percentile $samples.ToArray() 0.50
            p95 = Get-Percentile $samples.ToArray() 0.95
            max = [Math]::Round(($samples | Measure-Object -Maximum).Maximum, 2)
        }
    }
}

function Measure-ChatScenario {
    param(
        [string]$Name,
        [string]$Prompt
    )

    if (-not $BearerToken) {
        throw "BearerToken is required when a chat prompt is provided."
    }

    $handler = [System.Net.Http.HttpClientHandler]::new()
    $client = [System.Net.Http.HttpClient]::new($handler)
    $request = [System.Net.Http.HttpRequestMessage]::new(
        [System.Net.Http.HttpMethod]::Post,
        "$ApiBaseUrl/chat/stream"
    )
    $request.Headers.Authorization = `
        [System.Net.Http.Headers.AuthenticationHeaderValue]::new(
            "Bearer",
            $BearerToken
        )
    $payload = @{ message = $Prompt } | ConvertTo-Json -Compress
    $request.Content = [System.Net.Http.StringContent]::new(
        $payload,
        [Text.Encoding]::UTF8,
        "application/json"
    )

    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    $firstTokenMs = $null
    $eventTypes = @{}
    $eventBuffer = ""
    try {
        $response = $client.SendAsync(
            $request,
            [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        $headersMs = [Math]::Round($stopwatch.Elapsed.TotalMilliseconds, 2)
        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $reader = [System.IO.StreamReader]::new($stream, [Text.Encoding]::UTF8)
        while (-not $reader.EndOfStream) {
            $line = $reader.ReadLine()
            if (-not $line.StartsWith("data:")) { continue }
            $eventBuffer = $line.Substring(5).TrimStart()
            try {
                $event = $eventBuffer | ConvertFrom-Json
                $eventType = [string]$event.type
                if (-not $eventTypes.ContainsKey($eventType)) {
                    $eventTypes[$eventType] = 0
                }
                $eventTypes[$eventType]++
                if ($eventType -eq "token" -and $null -eq $firstTokenMs) {
                    $firstTokenMs = [Math]::Round(
                        $stopwatch.Elapsed.TotalMilliseconds,
                        2
                    )
                }
            } catch {
                if (-not $eventTypes.ContainsKey("malformed")) {
                    $eventTypes["malformed"] = 0
                }
                $eventTypes["malformed"]++
            }
        }
        $stopwatch.Stop()
        return [ordered]@{
            name = $Name
            status_code = [int]$response.StatusCode
            response_headers_ms = $headersMs
            first_token_ms = $firstTokenMs
            total_ms = [Math]::Round($stopwatch.Elapsed.TotalMilliseconds, 2)
            event_counts = $eventTypes
        }
    } finally {
        $stopwatch.Stop()
        if ($reader) { $reader.Dispose() }
        if ($stream) { $stream.Dispose() }
        if ($response) { $response.Dispose() }
        $request.Dispose()
        $client.Dispose()
        $handler.Dispose()
    }
}

try {
    $live = Invoke-WebRequest `
        -Uri "$ApiBaseUrl/health/live" `
        -TimeoutSec 5 `
        -SkipHttpErrorCheck
} catch {
    throw "API is not reachable at $ApiBaseUrl. Start it before collecting a runtime baseline."
}
if ($live.StatusCode -ne 200) {
    throw "API liveness returned HTTP $($live.StatusCode)."
}

$chatScenarios = [System.Collections.Generic.List[object]]::new()
if ($PureModelPrompt) {
    $chatScenarios.Add(
        (Measure-ChatScenario "pure_model" $PureModelPrompt)
    )
}
if ($ReadToolPrompt) {
    $chatScenarios.Add(
        (Measure-ChatScenario "read_tool" $ReadToolPrompt)
    )
}
if ($WriteConfirmationPrompt) {
    $chatScenarios.Add(
        (Measure-ChatScenario "write_confirmation" $WriteConfirmationPrompt)
    )
}

$result = [ordered]@{
    captured_at = (Get-Date).ToUniversalTime().ToString("o")
    api_base_url = $ApiBaseUrl
    process_idle = Get-BackendProcessSample
    endpoints = @(
        (Measure-GetEndpoint "readiness" "/health/ready")
        (Measure-GetEndpoint "catalog" "/catalog/shops")
    )
    chat_scenarios = $chatScenarios
    process_after = Get-BackendProcessSample
}

$outputDirectory = Split-Path -Parent $OutputPath
if ($outputDirectory) {
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
}
$result | ConvertTo-Json -Depth 8 | Set-Content `
    -LiteralPath $OutputPath `
    -Encoding utf8

Write-Host "Baseline written to $OutputPath"
$result | ConvertTo-Json -Depth 8
