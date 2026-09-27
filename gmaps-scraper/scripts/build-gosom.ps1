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

# A directory only counts as "already cloned" if it actually contains the
# expected source (not just an empty/partial dir left by an interrupted or
# failed clone), so a prior failure doesn't get skipped forever.
function Test-ValidClone($Dir, $MarkerRelPath) {
    return (Test-Path $Dir) -and (Test-Path (Join-Path $Dir $MarkerRelPath))
}

function Invoke-GitClone($Branch, $Url, $Dest) {
    if (Test-Path $Dest) {
        Write-Host "Removing incomplete clone at $Dest ..."
        Remove-Item -Recurse -Force $Dest
    }
    git clone --depth 1 --branch $Branch $Url $Dest
    if ($LASTEXITCODE -ne 0) {
        if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
        throw "git clone of $Url (branch $Branch) failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-ValidClone $GosomSrc "go.mod")) {
    Write-Host "Cloning google-maps-scraper $GosomVersion ..."
    Invoke-GitClone $GosomVersion "https://github.com/gosom/google-maps-scraper.git" $GosomSrc
}
if (-not (Test-ValidClone $ScrapemateSrc "adapters\fetchers\jshttp\jshttp.go")) {
    Write-Host "Cloning scrapemate $ScrapemateVersion ..."
    Invoke-GitClone $ScrapemateVersion "https://github.com/gosom/scrapemate.git" $ScrapemateSrc
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
    if ($LASTEXITCODE -ne 0) { throw "go mod edit -replace failed with exit code $LASTEXITCODE." }

    # A silent failure here (e.g. a bad go.mod, permissions) would otherwise build
    # against the UNPATCHED scrapemate and still report success, reintroducing the
    # Windows --single-process bug. Verify the replace directive actually landed.
    $ModJson = (& $GoExe mod edit -json) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw "go mod edit -json failed with exit code $LASTEXITCODE." }
    if ($ModJson -notmatch [regex]::Escape("../scrapemate")) {
        throw "go.mod replace directive for scrapemate is missing after 'go mod edit -replace' (would build against the unpatched scrapemate)."
    }

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
