[CmdletBinding()]
param(
    [string]$TaskName = "DealWatchPL-HourlyCollection"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

& schtasks.exe /Delete /TN $TaskName /F
if ($LASTEXITCODE -ne 0) {
    throw "Could not remove scheduled task '$TaskName'."
}

Write-Output "Removed '$TaskName'."
