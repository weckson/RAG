param(
    [string]$BaseUrl = "http://127.0.0.1:8080",
    [string]$ApiKey = "",
    [string]$KillFilePath = ".\KILL",
    [string]$DatabaseUrl = "",
    [int]$PropagationSeconds = 2,
    [int]$WaitForRejectSeconds = 0,
    [int]$StartupWaitSeconds = 10
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param(
        [string]$Check,
        [bool]$Passed,
        [string]$Detail
    )
    $item = [pscustomobject]@{
        Check  = $Check
        Passed = $Passed
        Detail = $Detail
    }
    $results.Add($item)
    $status = if ($Passed) { "PASS" } else { "FAIL" }
    Write-Host "[$status] $Check - $Detail"
}

function Get-Api {
    param([string]$Path)
    $uri = "{0}{1}" -f $BaseUrl.TrimEnd("/"), $Path
    if ([string]::IsNullOrWhiteSpace($ApiKey)) {
        return Invoke-RestMethod -Method Get -Uri $uri -TimeoutSec 10
    }
    return Invoke-RestMethod -Method Get -Uri $uri -Headers @{ "X-API-Key" = $ApiKey } -TimeoutSec 10
}

function Post-Api {
    param([string]$Path)
    $uri = "{0}{1}" -f $BaseUrl.TrimEnd("/"), $Path
    if ([string]::IsNullOrWhiteSpace($ApiKey)) {
        return Invoke-RestMethod -Method Post -Uri $uri -TimeoutSec 10
    }
    return Invoke-RestMethod -Method Post -Uri $uri -Headers @{ "X-API-Key" = $ApiKey } -TimeoutSec 10
}

function Wait-Health {
    param([int]$Seconds)
    $lastError = ""
    for ($i = 0; $i -lt $Seconds; $i++) {
        try {
            return (Get-Api "/health")
        }
        catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Seconds 1
        }
    }
    throw "health endpoint is not reachable at $BaseUrl/health after ${Seconds}s. Start app first: python -m src.app. last_error=$lastError"
}

function Resolve-DatabaseUrl {
    param([string]$InputUrl)

    if (-not [string]::IsNullOrWhiteSpace($InputUrl)) {
        return $InputUrl
    }

    if (Test-Path ".\.env") {
        $line = Get-Content ".\.env" | Where-Object { $_ -match "^\s*DATABASE_URL\s*=" } | Select-Object -First 1
        if ($line) {
            return ($line -split "=", 2)[1].Trim()
        }
    }
    return "sqlite:///./executor.db"
}

function Resolve-SqlitePath {
    param([string]$Url)
    if ($Url -match "^sqlite:///(.+)$") {
        return $Matches[1]
    }
    return $Url
}

Write-Host "Safety check started. BaseUrl=$BaseUrl"

$health = $null
try {
    $health = Wait-Health -Seconds $StartupWaitSeconds
    $props = $health.PSObject.Properties.Name
    $ok = (
        ($props -contains "kill_switch") -and
        ($props -contains "control_server_ready") -and
        ($props -contains "ibkr_connected") -and
        ($props -contains "signal_queue_size")
    )
    Add-Result "Health endpoint reachable" $ok ("fields=" + (($props -join ",")))
}
catch {
    Add-Result "Health endpoint reachable" $false $_.Exception.Message
    $results | Format-Table -AutoSize
    exit 1
}

$killFilePreExisted = Test-Path $KillFilePath
try {
    if (-not $killFilePreExisted) {
        New-Item -ItemType File -Path $KillFilePath -Force | Out-Null
    }
    Start-Sleep -Seconds $PropagationSeconds
    $healthFile = Get-Api "/health"
    Add-Result "File kill switch activates" ([bool]$healthFile.kill_switch) ("kill_switch=" + $healthFile.kill_switch)
}
catch {
    Add-Result "File kill switch activates" $false $_.Exception.Message
}
finally {
    if ((-not $killFilePreExisted) -and (Test-Path $KillFilePath)) {
        Remove-Item $KillFilePath -Force
    }
}

try {
    $killResp = Post-Api "/kill"
    $healthKilled = Get-Api "/health"
    Add-Result "POST /kill activates kill switch" ([bool]$healthKilled.kill_switch) ("response=" + ($killResp | ConvertTo-Json -Compress))
}
catch {
    Add-Result "POST /kill activates kill switch" $false $_.Exception.Message
}

$resolvedDbUrl = Resolve-DatabaseUrl -InputUrl $DatabaseUrl
$dbPath = Resolve-SqlitePath -Url $resolvedDbUrl
if (-not (Test-Path $dbPath)) {
    Add-Result "Database file exists" $false ("not found: " + $dbPath)
}
else {
    Add-Result "Database file exists" $true $dbPath

    $checkRejectPy = @"
import json
import sqlite3
import sys

db_path = r'''$dbPath'''
conn = sqlite3.connect(db_path)
rows = conn.execute(
    "SELECT status, reason, ts_ms FROM orders ORDER BY id DESC LIMIT 200"
).fetchall()
conn.close()
rejects = [r for r in rows if len(r) >= 2 and r[1] == "KILL_SWITCH_ACTIVE"]
print(json.dumps({"rows": len(rows), "kill_switch_rejects": len(rejects)}))
"@
    try {
        $raw = $checkRejectPy | python -
        $obj = $raw | ConvertFrom-Json
        Add-Result "Orders table readable" $true ("rows=" + $obj.rows)
        if ($obj.kill_switch_rejects -gt 0) {
            Add-Result "Found KILL_SWITCH_ACTIVE rejections" $true ("count=" + $obj.kill_switch_rejects)
        }
        elseif ($WaitForRejectSeconds -gt 0) {
            $deadline = (Get-Date).AddSeconds($WaitForRejectSeconds)
            $found = $false
            while ((Get-Date) -lt $deadline) {
                Start-Sleep -Seconds 5
                $rawPoll = $checkRejectPy | python -
                $objPoll = $rawPoll | ConvertFrom-Json
                if ($objPoll.kill_switch_rejects -gt 0) {
                    Add-Result "Found KILL_SWITCH_ACTIVE rejections" $true ("count=" + $objPoll.kill_switch_rejects)
                    $found = $true
                    break
                }
            }
            if (-not $found) {
                Add-Result "Found KILL_SWITCH_ACTIVE rejections" $false ("none found within " + $WaitForRejectSeconds + "s; wait for strategy signals")
            }
        }
        else {
            Add-Result "Found KILL_SWITCH_ACTIVE rejections" $false "none found yet; run with -WaitForRejectSeconds 120 to wait for live signals"
        }
    }
    catch {
        Add-Result "Orders table readable" $false $_.Exception.Message
    }
}

Write-Host ""
Write-Host "Summary"
$results | Format-Table -AutoSize

$failed = $results | Where-Object { -not $_.Passed }
if ($failed.Count -gt 0) {
    Write-Host ""
    Write-Host "At least one check failed."
    exit 1
}

Write-Host ""
Write-Host "All checks passed."
exit 0
