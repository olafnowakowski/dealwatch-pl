[CmdletBinding()]
param(
    [string]$TaskName = "DealWatchPL-HourlyCollection"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$runner = Join-Path $PSScriptRoot "run-hourly-collection.ps1"
$powerShell = Join-Path ([Environment]::SystemDirectory) "WindowsPowerShell\v1.0\powershell.exe"
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Missing scheduler runner at $runner."
}
if (-not (Test-Path -LiteralPath $powerShell)) {
    throw "Missing Windows PowerShell executable at $powerShell."
}

$taskCommand = "`"$powerShell`" -NoProfile -ExecutionPolicy Bypass -File `"$runner`""
& schtasks.exe /Create /TN $TaskName /TR $taskCommand /SC HOURLY /MO 1 /RU $currentUser /IT /F
if ($LASTEXITCODE -ne 0) {
    throw "Could not register scheduled task '$TaskName'."
}

Write-Output "Registered '$TaskName' for hourly x-kom monitoring."
Write-Output "Run it immediately with: schtasks.exe /Run /TN `"$TaskName`""
