[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$dataDirectory = Join-Path $projectRoot "data"
$logDirectory = Join-Path $dataDirectory "logs"
$logFile = Join-Path $logDirectory "hourly-monitoring.log"
$lockFile = Join-Path $dataDirectory "hourly-collection.lock"
$lockStream = $null
$locationPushed = $false

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
Push-Location -LiteralPath $projectRoot
$locationPushed = $true

function Write-MonitoringLog {
    param(
        [Parameter(Mandatory = $true)][string]$Level,
        [Parameter(Mandatory = $true)][string]$Message
    )

    $timestamp = (Get-Date).ToUniversalTime().ToString("o")
    "$timestamp [$Level] $Message" | Out-File -LiteralPath $logFile -Append -Encoding utf8
}

function Send-MonitoringFailureNotice {
    param([Parameter(Mandatory = $true)][string]$Message)

    try {
        $msg = Get-Command msg.exe -ErrorAction Stop
        & $msg.Source $env:USERNAME /TIME:60 "DealWatch monitoring failed: $Message" | Out-Null
    }
    catch {
        Write-MonitoringLog -Level "WARN" -Message "Could not show local failure notice: $($_.Exception.Message)"
    }
}

try {
    if (Test-Path -LiteralPath $lockFile) {
        $age = (Get-Date).ToUniversalTime() - (Get-Item -LiteralPath $lockFile).LastWriteTimeUtc
        $lockOwnerText = Get-Content -LiteralPath $lockFile -Raw
        if ($null -eq $lockOwnerText) {
            $lockOwnerText = [string]::Empty
        }
        $lockOwnerText = $lockOwnerText.Trim()
        $lockOwnerId = 0
        $ownerIsRunning = $false
        if ([int]::TryParse($lockOwnerText, [ref]$lockOwnerId)) {
            $ownerIsRunning = $null -ne (Get-Process -Id $lockOwnerId -ErrorAction SilentlyContinue)
        }
        if ($age.TotalHours -ge 2 -or (-not $ownerIsRunning -and $age.TotalSeconds -ge 10)) {
            Remove-Item -LiteralPath $lockFile -Force
            Write-MonitoringLog -Level "WARN" -Message "Removed stale monitoring lock."
        }
    }

    try {
        $lockStream = [System.IO.File]::Open(
            $lockFile,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        $lockBytes = [System.Text.Encoding]::UTF8.GetBytes($PID.ToString())
        $lockStream.Write($lockBytes, 0, $lockBytes.Length)
        $lockStream.Flush()
    }
    catch [System.IO.IOException] {
        Write-MonitoringLog -Level "INFO" -Message "Skipped overlapping monitoring run."
        exit 0
    }

    $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Missing virtual environment Python at $python. Run 'uv sync --all-groups' first."
    }

    Write-MonitoringLog -Level "INFO" -Message "Starting hourly x-kom monitoring."
    $commandOutput = & $python -m dealwatch xkom monitor-gpus --send --quiet 2>&1
    $exitCode = $LASTEXITCODE
    foreach ($line in $commandOutput) {
        Write-MonitoringLog -Level "INFO" -Message $line.ToString()
    }
    if ($exitCode -ne 0) {
        throw "Monitoring command exited with code $exitCode."
    }
    Write-MonitoringLog -Level "INFO" -Message "Hourly x-kom monitoring completed."
}
catch {
    Write-MonitoringLog -Level "ERROR" -Message $_.Exception.Message
    Send-MonitoringFailureNotice -Message "See $logFile for details."
    Write-Error $_
    exit 1
}
finally {
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
        Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
    }
    if ($locationPushed) {
        Pop-Location
    }
}
