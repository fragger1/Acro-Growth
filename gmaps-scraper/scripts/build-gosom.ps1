$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Bin = Join-Path $Root "bin"
$Exe = Join-Path $Bin "google-maps-scraper.exe"

$GosomVersion = "v1.18.1"
$ScrapemateVersion = "v1.4.0"
$PatchFile = Join-Path $Root "patches\scrapemate-v1.4.0-windows-no-single-process.patch"

New-Item -ItemType Directory -Force $Bin | Out-Null
$Src = Join-Path $Bin "src"
New-Item -ItemType Directory -Force $Src | Out-Null

# --- 1. Portable Go toolchain (no system install, no PATH/registry changes) ---
$GoRoot = Join-Path $Bin "go"
$GoExe = Join-Path $GoRoot "bin\go.exe"
if (-not (Test-Path $GoExe)) {
    Write-Host "Fetching latest stable Go version ..."
    $GoVersion = (Invoke-WebRequest "https://go.dev/VERSION?m=text" -UseBasicParsing).Content -split "`n" | Select-Object -First 1
    $GoVersion = $GoVersion.Trim()
    $GoZipUrl = "https://go.dev/dl/$GoVersion.windows-amd64.zip"
    $GoZip = Join-Path $Bin "$GoVersion.windows-amd64.zip"
    Write-Host "Downloading $GoZipUrl ..."
    Invoke-WebRequest $GoZipUrl -OutFile $GoZip
    Write-Host "Extracting Go to $Bin ..."
    Expand-Archive -Path $GoZip -DestinationPath $Bin -Force
    Remove-Item $GoZip
}
if (-not (Test-Path $GoExe)) { throw "Portable Go extraction failed: $GoExe not found." }
& $GoExe version

# --- 2. Clone gosom and scrapemate at pinned tags (skip if already present) ---
$GosomSrc = Join-Path $Src "gosom"
$ScrapemateSrc = Join-Path $Src "scrapemate"

if (-not (Test-Path $GosomSrc)) {
    Write-Host "Cloning google-maps-scraper $GosomVersion ..."
    git clone --depth 1 --branch $GosomVersion https://github.com/gosom/google-maps-scraper.git $GosomSrc
}
if (-not (Test-Path $ScrapemateSrc)) {
    Write-Host "Cloning scrapemate $ScrapemateVersion ..."
    git clone --depth 1 --branch $ScrapemateVersion https://github.com/gosom/scrapemate.git $ScrapemateSrc
}

# --- 3. Apply the Windows --single-process patch (skip if already applied) ---
# Native stderr redirected through PowerShell 5.1 becomes a terminating ErrorRecord
# under $ErrorActionPreference = "Stop" even on a expected/non-fatal "not applied yet"
# result, so relax it just for this check and restore it right after.
$PrevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
git -C $ScrapemateSrc apply --reverse --check $PatchFile 2>$null 1>$null
$AlreadyApplied = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $PrevEAP
if (-not $AlreadyApplied) {
    Write-Host "Applying Windows --single-process patch ..."
    git -C $ScrapemateSrc apply $PatchFile
    if ($LASTEXITCODE -ne 0) { throw "Failed to apply patch to scrapemate." }
} else {
    Write-Host "Patch already applied, skipping."
}

# --- 4. Build gosom against the patched local scrapemate ---
$GoPath = Join-Path $Bin "gopath"
$GoCache = Join-Path $Bin "gocache"
$GoModCache = Join-Path $Bin "gomodcache"
New-Item -ItemType Directory -Force $GoPath, $GoCache, $GoModCache | Out-Null

$env:GOTOOLCHAIN = "local"
$env:GOPATH = $GoPath
$env:GOCACHE = $GoCache
$env:GOMODCACHE = $GoModCache
$env:GOFLAGS = ""
$env:CGO_ENABLED = "0"

Push-Location $GosomSrc
try {
    Write-Host "Wiring go.mod to the local patched scrapemate ..."
    & $GoExe mod edit -replace "github.com/gosom/scrapemate=../scrapemate"

    Write-Host "Building google-maps-scraper.exe (this can take a few minutes the first time) ..."
    # `go build .` alone resolves only the main package's own dependency graph
    # (a few hundred MB); `go mod tidy` would additionally pull in gosom's
    # go.mod-listed dev tooling (golangci-lint and its ~300 linter
    # dependencies), which is unrelated to producing the binary and much
    # slower for no benefit here.
    & $GoExe build -o (Join-Path $Bin "google-maps-scraper.exe") .
    if ($LASTEXITCODE -ne 0) { throw "go build failed. If this is a CGO or Go-toolchain-version error, a newer local Go than the portable download may be required; report this instead of guessing further." }
} finally {
    Pop-Location
}

if (-not (Test-Path $Exe)) { throw "Build did not produce $Exe." }
Write-Host "Built patched gosom:"
& $Exe -version
