$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Gmaps = Join-Path $Root ".venv\Scripts\gmaps.exe"
if (-not (Test-Path $Gmaps)) { throw "Run scripts/setup.ps1 first." }

$Action = New-ScheduledTaskAction -Execute $Gmaps -Argument "run --scheduled" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At 1am
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 12) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "GMaps Scraper Nightly" -Action $Action -Trigger $Trigger `
    -Settings $Settings -Description "Google Maps lead scraper nightly run" -Force | Out-Null
Write-Host "Registered 'GMaps Scraper Nightly' (daily 1:00 AM, runs when available if missed)."
