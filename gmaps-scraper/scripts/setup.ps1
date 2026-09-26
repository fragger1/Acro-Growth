$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Bin = Join-Path $Root "bin"
$Exe = Join-Path $Bin "google-maps-scraper.exe"

# The published v1.18.1 release binary crashes on Windows (Chromium launched with
# --single-process returns an empty page -> gosom logs "unexpected page type" and
# every search silently returns 0 results). We build gosom from source against a
# patched scrapemate instead. See scripts/build-gosom.ps1 and
# patches/scrapemate-v1.4.0-windows-no-single-process.patch, and
# https://github.com/gosom/google-maps-scraper/issues/322
if (Test-Path $Exe) {
    Write-Host "Removing existing (possibly unpatched release) gosom binary ..."
    Remove-Item $Exe -Force
}
& (Join-Path $PSScriptRoot "build-gosom.ps1")

if (-not (Test-Path (Join-Path $Root ".venv"))) {
    py -3.13 -m venv (Join-Path $Root ".venv")
}
& (Join-Path $Root ".venv\Scripts\python.exe") -m pip install -q -e "$Root[dev]"
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Warning "No .env found. Copy .env.example to .env and fill it in."
}
Write-Host "Setup complete."
