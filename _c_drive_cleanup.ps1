<#
.SYNOPSIS
    C: drive cleanup helper for user 'song'.
    Tiered cleanup: A = safe caches, B = user-decided app data, D = system-level.
    Optional one-shot redirect of Gradle / NuGet / npm / pip caches to another drive.

.DESCRIPTION
    Every destructive step is:
      - guarded by an opt-in switch or interactive Y/N prompt
      - previewed when -WhatIf is set
      - wrapped in try/catch so a failure does not abort the run
      - logged to a timestamped .log file next to this script

    The script NEVER touches:
      - Documents / Desktop / Pictures / Videos / Downloads / OneDrive user files
      - Program Files installed apps
      - Package Cache (needed by MSI repair/uninstall)
      - Any project source code

.PARAMETER Mode
    A           : safe caches only
    AB          : A + user-decided app caches (Playwright / Android / Trae / Ollama / etc.)
    Full        : A + B + D (D needs admin)
    Interactive : default; asks per item

.PARAMETER Redirect
    Path on another drive (e.g. E:\dev-cache). Existing Gradle / NuGet / npm / pip
    caches are moved there via robocopy /MOVE and env vars are set for the user scope.

.PARAMETER WhatIf
    Dry run. Prints what would be deleted but changes nothing on disk.

.PARAMETER LogPath
    Alternate log file path. Default: <script dir>\c_cleanup_<timestamp>.log

.EXAMPLE
    .\_c_drive_cleanup.ps1 -Mode A -WhatIf

.EXAMPLE
    .\_c_drive_cleanup.ps1 -Mode A

.EXAMPLE
    .\_c_drive_cleanup.ps1 -Mode AB -Redirect E:\dev-cache

.EXAMPLE
    # Elevated full run:
    Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','.\_c_drive_cleanup.ps1','-Mode','Full'
#>

[CmdletBinding()]
param(
    [ValidateSet("A", "AB", "Full", "Interactive")]
    [string]$Mode = "Interactive",

    [string]$Redirect = "",

    [switch]$WhatIf,

    [string]$LogPath = ""
)

$ErrorActionPreference = 'Continue'
$script:UserHome = $env:USERPROFILE
$script:LocalApp = $env:LOCALAPPDATA
$script:RoamApp  = $env:APPDATA

# ------------------------------------------------------------------
# log helpers
# ------------------------------------------------------------------
if (-not $LogPath) {
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $LogPath = Join-Path $PSScriptRoot "c_cleanup_$ts.log"
}
if (-not (Test-Path $PSScriptRoot)) {
    $LogPath = Join-Path $env:TEMP "c_cleanup_$ts.log"
}

function Log {
    param([string]$Level, [string]$Message)
    $line = "[{0}] {1,-6} {2}" -f (Get-Date -Format "HH:mm:ss"), $Level, $Message
    Write-Host $line
    try { Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8 } catch { }
}

# ------------------------------------------------------------------
# size helpers
# ------------------------------------------------------------------
function Get-PathSizeBytes {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return 0 }
    if (-not (Test-Path -LiteralPath $Path)) { return 0 }
    try {
        $item = Get-Item -LiteralPath $Path -Force
        if ($item.PSIsContainer) {
            $s = (Get-ChildItem -LiteralPath $Path -Recurse -Force -File `
                    -ErrorAction SilentlyContinue |
                  Measure-Object -Property Length -Sum).Sum
        } else {
            $s = $item.Length
        }
        if ($null -eq $s) { $s = 0 }
        return [long]$s
    } catch { return 0 }
}

function Format-GB {
    param([double]$Bytes)
    return [math]::Round($Bytes / 1GB, 2)
}

# ------------------------------------------------------------------
# operation helpers
# ------------------------------------------------------------------
function Invoke-Delete {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path)) {
        Log "INFO" ("Skip (missing): {0}" -f $Label)
        return 0
    }
    $before = Get-PathSizeBytes $Path
    if ($WhatIf) {
        Log "WHATIF" ("Would delete {0} GB : {1} ({2})" -f (Format-GB $before), $Label, $Path)
        return $before
    }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop -Confirm:$false
        Log "OK" ("Deleted {0} GB : {1}" -f (Format-GB $before), $Label)
        return $before
    } catch {
        Log "FAIL" ("Cannot delete {0} ({1}): {2}" -f $Label, $Path, $_.Exception.Message)
        return 0
    }
}

function Invoke-EmptyDir {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path)) {
        Log "INFO" ("Skip (missing): {0}" -f $Label)
        return 0
    }
    $before = Get-PathSizeBytes $Path
    if ($WhatIf) {
        Log "WHATIF" ("Would empty {0} GB contents of {1} ({2})" -f (Format-GB $before), $Label, $Path)
        return $before
    }
    $failCount = 0
    Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue | ForEach-Object {
        try {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop
        } catch {
            $failCount++
        }
    }
    $after = Get-PathSizeBytes $Path
    $freed = [math]::Max([long]0, [long]($before - $after))
    if ($failCount -gt 0) {
        Log "WARN" ("Emptied {0} GB : {1}  (skipped {2} locked files)" -f (Format-GB $freed), $Label, $failCount)
    } else {
        Log "OK" ("Emptied {0} GB : {1}" -f (Format-GB $freed), $Label)
    }
    return $freed
}

function Invoke-RecycleBinEmpty {
    param([string]$Label)
    $before = Get-PathSizeBytes 'C:\$Recycle.Bin'
    if ($WhatIf) {
        Log "WHATIF" ("Would empty Recycle Bin ({0} GB)" -f (Format-GB $before))
        return $before
    }
    try {
        # Preferred: clear through Shell API so all user SIDs get cleaned
        $shell = New-Object -ComObject Shell.Application
        $rb = $shell.NameSpace(10)
        $rb.Items() | ForEach-Object { }
        $rb.Self.InvokeVerb("Empty Recycle Bin")
        Start-Sleep -Seconds 2
    } catch {
        Log "WARN" ("Shell API failed, fallback to Remove-Item: {0}" -f $_.Exception.Message)
    }
    try {
        Get-ChildItem -LiteralPath 'C:\$Recycle.Bin' -Force -ErrorAction SilentlyContinue |
            ForEach-Object {
                try { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction Stop } catch { }
            }
    } catch { }
    $after = Get-PathSizeBytes 'C:\$Recycle.Bin'
    $freed = [math]::Max([long]0, [long]($before - $after))
    Log "OK" ("Emptied Recycle Bin: {0} GB" -f (Format-GB $freed))
    return $freed
}

function Invoke-Command {
    param([string]$Label, [scriptblock]$Block)
    if ($WhatIf) {
        Log "WHATIF" ("Would run command: {0}" -f $Label)
        return 0
    }
    try {
        $before = (Get-PSDrive C).Free
        & $Block 2>&1 | Out-Null
        Start-Sleep -Milliseconds 300
        $after = (Get-PSDrive C).Free
        $delta = [math]::Max([long]0, [long]($after - $before))
        Log "OK" ("Ran {0} (freed {1} GB)" -f $Label, (Format-GB $delta))
        return $delta
    } catch {
        Log "FAIL" ("Command failed ({0}): {1}" -f $Label, $_.Exception.Message)
        return 0
    }
}

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p  = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ------------------------------------------------------------------
# catalog
# ------------------------------------------------------------------
$catalog = @()

# --- Tier A: safe caches (auto-regenerated) ---
$catalog += [pscustomobject]@{ Tier='A'; Id='A1'; Label='Recycle Bin'
    Action='RecycleBin'; Path='C:\$Recycle.Bin'
    Description='Empties Windows Recycle Bin. Contents already deleted by user.' }

$catalog += [pscustomobject]@{ Tier='A'; Id='A2'; Label='LLDB module cache'
    Action='Empty'; Path=(Join-Path $UserHome '.lldb\module_cache')
    Description='LLDB debugger module cache. Regenerated on next debug session.' }

$catalog += [pscustomobject]@{ Tier='A'; Id='A3'; Label='User TEMP'
    Action='Empty'; Path=$env:TEMP
    Description='Per-user temp. In-use files are auto-skipped.' }

$catalog += [pscustomobject]@{ Tier='A'; Id='A4'; Label='Gradle caches (deps + build)'
    Action='Empty'; Path=(Join-Path $UserHome '.gradle\caches')
    Description='Gradle dependency + build cache. Re-download on next build (network cost).' }

$catalog += [pscustomobject]@{ Tier='A'; Id='A10'; Label='Gradle wrapper distributions'
    Action='Empty'; Path=(Join-Path $UserHome '.gradle\wrapper\distributions')
    Description='Cached Gradle distributions. Re-download on next wrapper run.' }

$catalog += [pscustomobject]@{ Tier='A'; Id='A5'; Label='Gradle daemon logs'
    Action='Empty'; Path=(Join-Path $UserHome '.gradle\daemon')
    Description='Old Gradle daemon logs. Safe.' }

$catalog += [pscustomobject]@{ Tier='A'; Id='A6'; Label='NuGet global packages'
    Action='Empty'; Path=(Join-Path $UserHome '.nuget\packages')
    Description='.NET package cache. Re-download on next restore.' }

$catalog += [pscustomobject]@{ Tier='A'; Id='A7'; Label='npm cache'
    Action='Empty'; Path=(Join-Path $LocalApp 'npm-cache')
    Description='npm offline cache. Safe.' }

$catalog += [pscustomobject]@{ Tier='A'; Id='A8'; Label='pip wheel cache'
    Action='Empty'; Path=(Join-Path $LocalApp 'pip\Cache')
    Description='pip cache. Safe.' }

$catalog += [pscustomobject]@{ Tier='A'; Id='A9'; Label='Windows Error Reporting queue'
    Action='Empty'; Path=(Join-Path $env:PROGRAMDATA 'Microsoft\Windows\WER\ReportQueue')
    Description='Pending WER crash reports. Safe to purge.' }

# --- Tier B: user-decided app caches ---
$catalog += [pscustomobject]@{ Tier='B'; Id='B1'; Label='Playwright browsers'
    Action='Empty'; Path=(Join-Path $LocalApp 'ms-playwright')
    Description='Cached Chromium/Firefox/WebKit for Playwright. Re-install via: npx playwright install' }

$catalog += [pscustomobject]@{ Tier='B'; Id='B2'; Label='Android SDK + emulator'
    Action='Empty'; Path=(Join-Path $LocalApp 'Android\Sdk')
    Description='Android SDK (~12 GB). Only if no more Android dev. Re-installable via Android Studio.' }

$catalog += [pscustomobject]@{ Tier='B'; Id='B3'; Label='Trae IDE local config'
    Action='Empty'; Path=(Join-Path $UserHome '.trae-cn')
    Description='Trae IDE local config. Only if Trae is not used.' }

$catalog += [pscustomobject]@{ Tier='B'; Id='B4'; Label='Trae SOLO CN roaming'
    Action='Empty'; Path=(Join-Path $RoamApp 'TRAE SOLO CN')
    Description='Trae SOLO CN roaming data. Only if Trae is not used.' }

$catalog += [pscustomobject]@{ Tier='B'; Id='B5'; Label='understand-anything cache'
    Action='Empty'; Path=(Join-Path $UserHome '.understand-anything')
    Description='Old understand-* plugin cache.' }

$catalog += [pscustomobject]@{ Tier='B'; Id='B6'; Label='understand-anything-plugin cache'
    Action='Empty'; Path=(Join-Path $UserHome '.understand-anything-plugin')
    Description='Old understand-* plugin cache.' }

$catalog += [pscustomobject]@{ Tier='B'; Id='B7'; Label='Ollama install dir'
    Action='Empty'; Path=(Join-Path $LocalApp 'Programs\Ollama')
    Description='Ollama binary + downloaded models (~3 GB). Only if you do NOT use Ollama.' }

$catalog += [pscustomobject]@{ Tier='B'; Id='B8'; Label='pnpm store'
    Action='Empty'; Path=(Join-Path $LocalApp 'pnpm')
    Description='pnpm content-addressable store. Only if pnpm projects are dormant.' }

$catalog += [pscustomobject]@{ Tier='B'; Id='B9'; Label='uv cache'
    Action='Empty'; Path=(Join-Path $LocalApp 'uv')
    Description='uv (Python package manager) cache. Regenerated as needed.' }

$catalog += [pscustomobject]@{ Tier='B'; Id='B10'; Label='Postman cache'
    Action='Empty'; Path=(Join-Path $LocalApp 'Postman')
    Description='Postman app cache (~0.88 GB). Re-downloadable collections remain in cloud.' }

$catalog += [pscustomobject]@{ Tier='B'; Id='B11'; Label='VS Code extensions cache'
    Action='Empty'; Path=(Join-Path $UserHome '.vscode')
    Description='VS Code extensions dir. Extensions must be re-installed if you use VS Code.' }

# --- Tier D: system-level (requires admin) ---
$catalog += [pscustomobject]@{ Tier='D'; Id='D1'; Label='Windows Temp'
    Action='Empty'; Path='C:\Windows\Temp'
    Description='System-wide temp. Needs admin.' }

$catalog += [pscustomobject]@{ Tier='D'; Id='D2'; Label='Windows Update staged downloads'
    Action='Empty'; Path='C:\Windows\SoftwareDistribution\Download'
    Description='Pending WU files. Needs admin + WU service stopped first.' }

$catalog += [pscustomobject]@{ Tier='D'; Id='D3'; Label='Delivery Optimization cache'
    Action='Empty'; Path='C:\Windows\SoftwareDistribution\DeliveryOptimization'
    Description='Shared update cache. Needs admin.' }

$catalog += [pscustomobject]@{ Tier='D'; Id='D4'; Label='Windows Defender quarantine (safe)'
    Action='Empty'; Path=(Join-Path $env:PROGRAMDATA 'Microsoft\Windows Defender\Quarantine')
    Description='Only if you trust no quarantined file needs to be restored.' }

$catalog += [pscustomobject]@{ Tier='D'; Id='D5'; Label='DISM component store cleanup'
    Action='Command'; Path=''
    Description='Shrink WinSxS (9.78 GB). Non-destructive; keeps uninstall ability.' }

$catalog += [pscustomobject]@{ Tier='D'; Id='D6'; Label='DISM ResetBase (aggressive)'
    Action='Command'; Path=''
    Description='Removes superseded components. Cannot uninstall existing updates afterwards.' }

# ------------------------------------------------------------------
# command handlers
# ------------------------------------------------------------------
$script:CommandCatalog = @{
    'D5' = { & Dism.exe /Online /Cleanup-Image /StartComponentCleanup }
    'D6' = { & Dism.exe /Online /Cleanup-Image /StartComponentCleanup /ResetBase }
}

function Invoke-CleanupItem {
    param($item)
    switch ($item.Action) {
        'RecycleBin' { return Invoke-RecycleBinEmpty -Label $item.Label }
        'Empty'      { return Invoke-EmptyDir   -Path $item.Path -Label $item.Label }
        'Delete'     { return Invoke-Delete     -Path $item.Path -Label $item.Label }
        'Command'    {
            $blk = $script:CommandCatalog[$item.Id]
            if ($null -eq $blk) { Log "FAIL" "No handler for $($item.Id)"; return 0 }
            return Invoke-Command -Label $item.Label -Block $blk
        }
    }
    return 0
}

# ------------------------------------------------------------------
# cache redirect
# ------------------------------------------------------------------
function Invoke-CacheRedirect {
    param([string]$Root)

    Log "INFO" "Cache redirection target: $Root"

    if ($WhatIf) {
        Log "WHATIF" "Would create $Root and move Gradle/NuGet/npm/pip caches there."
        return
    }

    if (-not (Test-Path -LiteralPath $Root)) {
        try { New-Item -ItemType Directory -Path $Root -Force | Out-Null }
        catch { Log "FAIL" "Cannot create $Root : $($_.Exception.Message)"; return }
    }

    # Warn if target drive has less than 20 GB free
    $drive = (Get-Item -LiteralPath $Root).Root.Name.TrimEnd('\', ':')
    $freeGB = [math]::Round((Get-PSDrive $drive).Free / 1GB, 2)
    if ($freeGB -lt 20) {
        Log "WARN" "Target drive $drive has only $freeGB GB free. Consider a different location."
    }

    $map = @(
        @{ Name='Gradle';  From=(Join-Path $UserHome '.gradle')
           To=(Join-Path $Root 'gradle');     Env='GRADLE_USER_HOME';  Npm=$false }
        @{ Name='NuGet';   From=(Join-Path $UserHome '.nuget')
           To=(Join-Path $Root 'nuget');      Env='NUGET_PACKAGES';    Npm=$false }
        @{ Name='pip';     From=(Join-Path $LocalApp 'pip\Cache')
           To=(Join-Path $Root 'pip-cache');  Env='PIP_CACHE_DIR';     Npm=$false }
        @{ Name='npm';     From=(Join-Path $LocalApp 'npm-cache')
           To=(Join-Path $Root 'npm-cache');  Env='';                  Npm=$true }
        @{ Name='uv';      From=(Join-Path $LocalApp 'uv')
           To=(Join-Path $Root 'uv');         Env='UV_CACHE_DIR';      Npm=$false }
    )

    foreach ($m in $map) {
        $src = $m.From
        $dst = $m.To
        if (-not (Test-Path -LiteralPath $dst)) {
            New-Item -ItemType Directory -Path $dst -Force | Out-Null
        }
        if (-not (Test-Path -LiteralPath $src)) {
            Log "INFO" ("{0}: source missing ({1}), env will point to {2}" -f $m.Name, $src, $dst)
        } else {
            Log "INFO" ("Moving {0} cache: {1} -> {2}" -f $m.Name, $src, $dst)
            $rc = @($src, $dst, '/E', '/MOVE', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1')
            try {
                & robocopy.exe @rc | Out-Null
                $code = $LASTEXITCODE
                if ($code -ge 8) {
                    Log "FAIL" ("robocopy {0} failed exit={1} (source may still exist on C)" -f $m.Name, $code)
                } else {
                    Log "OK" ("Moved {0} cache (robocopy exit={1})" -f $m.Name, $code)
                }
            } catch {
                Log "FAIL" ("robocopy {0} threw: {1}" -f $m.Name, $_.Exception.Message)
            }
        }
        if ($m.Env) {
            [Environment]::SetEnvironmentVariable($m.Env, $dst, 'User')
            Log "OK" ("User env {0} = {1}" -f $m.Env, $dst)
        }
        if ($m.Npm) {
            $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
            if ($npmCmd) {
                try {
                    & npm config set cache $dst --location=user 2>&1 | Out-Null
                    Log "OK" ("npm config set cache = $dst")
                } catch { Log "WARN" "npm config set failed" }
            } else {
                Log "INFO" "npm not found on PATH; skipping npm config"
            }
        }
    }

    Log "INFO" "Cache redirection complete. Restart terminal / IDE to pick up new env vars."
}

# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  C: drive cleanup  -  Mode: $Mode" -ForegroundColor Cyan
Write-Host ("  WhatIf (dry-run): {0}" -f [bool]$WhatIf) -ForegroundColor Cyan
Write-Host ("  Redirect caches to: {0}" -f ($(if ($Redirect) { $Redirect } else { "(skip)" }))) -ForegroundColor Cyan
Write-Host ("  Log: {0}" -f $LogPath) -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

$isAdmin = Test-IsAdmin
Write-Host ("Admin elevated: {0}" -f $isAdmin)
if (-not $isAdmin) {
    Log "WARN" "Not elevated. Tier D items that need admin will be skipped or partially fail."
}

$prevFree = (Get-PSDrive C).Free
$totalFreed = 0
$totalSkipped = 0
$totalFailed = 0

$tiers = switch ($Mode) {
    'A'           { @('A') }
    'AB'          { @('A', 'B') }
    'Full'        { @('A', 'B', 'D') }
    'Interactive' { @('A', 'B', 'D') }
}

foreach ($tier in $tiers) {
    Write-Host ""
    Write-Host "--- Tier $tier ---" -ForegroundColor Yellow
    $items = $catalog | Where-Object Tier -eq $tier
    foreach ($item in $items) {
        $sizeBytes = if ($item.Path) { Get-PathSizeBytes $item.Path } else { 0 }
        $sizeGB = Format-GB $sizeBytes

        # Pre-flight skip when nothing to clean
        if ($item.Action -ne 'Command' -and $sizeBytes -eq 0) {
            Log "INFO" ("Skip {0} {1}: nothing to clean" -f $item.Id, $item.Label)
            continue
        }

        # Decide whether to run this item
        $do = $true
        if ($Mode -eq 'Interactive') {
            Write-Host ""
            Write-Host ("[{0}] {1}  [{2} GB]" -f $item.Id, $item.Label, $sizeGB) -ForegroundColor Cyan
            Write-Host ("      {0}" -f $item.Description)
            if ($item.Path) { Write-Host ("      path: {0}" -f $item.Path) -ForegroundColor DarkGray }
            $ans = Read-Host "      run this step? [y/N/s=skip/q=quit]"
            if ($ans -match '^[Qq]') { break }
            $do = ($ans -match '^[Yy]')
        }

        if (-not $do) {
            Log "SKIP" "$($item.Id) $($item.Label)"
            $totalSkipped++
            continue
        }

        # D-tier admin gate
        if ($item.Tier -eq 'D' -and -not $isAdmin) {
            Log "WARN" ("Skip {0} {1}: requires admin" -f $item.Id, $item.Label)
            $totalSkipped++
            continue
        }

        $freed = Invoke-CleanupItem -item $item
        if ($freed -gt 0) { $totalFreed += $freed } else { $totalFailed++ }
    }
}

if ($Redirect) {
    Write-Host ""
    Write-Host "--- Cache redirection ---" -ForegroundColor Yellow
    Invoke-CacheRedirect -Root $Redirect
}

$nowFree = (Get-PSDrive C).Free

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host ("Reported reclaimed (sum of item sizes at scan time): {0} GB" -f (Format-GB $totalFreed)) -ForegroundColor Green
Write-Host ("Actual C: free   before {0} GB -> after {1} GB  (delta {2} GB)" -f `
    (Format-GB $prevFree), (Format-GB $nowFree), (Format-GB ($nowFree - $prevFree))) -ForegroundColor Green
Write-Host ("Skipped {0}   Failed {1}" -f $totalSkipped, $totalFailed)
Write-Host "Log: $LogPath"
Write-Host "==================================================" -ForegroundColor Green

if ($Mode -eq 'Interactive') {
    Write-Host ""
    Read-Host "Press Enter to close"
}
