$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Version = "1.18.1"
$Bin = Join-Path $Root "bin"
$Exe = Join-Path $Bin "google-maps-scraper.exe"

New-Item -ItemType Directory -Force $Bin | Out-Null
if (-not (Test-Path $Exe)) {
    $Url = "https://github.com/gosom/google-maps-scraper/releases/download/v$Version/google_maps_scraper-$Version-windows-amd64.exe"
    Write-Host "Downloading gosom v$Version ..."
    Invoke-WebRequest $Url -OutFile $Exe
}
& $Exe -version

if (-not (Test-Path (Join-Path $Root ".venv"))) {
    py -3.13 -m venv (Join-Path $Root ".venv")
}
& (Join-Path $Root ".venv\Scripts\python.exe") -m pip install -q -e "$Root[dev]"
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Warning "No .env found. Copy .env.example to .env and fill it in."
}
Write-Host "Setup complete."
