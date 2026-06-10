# =========================================================================
#  DateClock manual cleanup
#
#  Use this when the normal uninstall didn't finish (e.g., the install
#  folder was deleted before Windows could run the uninstaller). It also
#  removes anything left over from the older "BigClock" name.
#
#  Double-click Cleanup.bat to run it. It will:
#    1. Stop any running DateClock / BigClock process.
#    2. Remove Apps & Features registry entries (HKLM + HKCU for both names).
#    3. Remove Run-at-logon entries (HKCU for both names).
#    4. Remove Start Menu / Desktop shortcuts (all-users and per-user).
#    5. Remove the install folders if any survived.
#    6. Ask before removing your saved settings in %APPDATA%.
#
#  Needs admin to clean HKLM entries and C:\Program Files folders. The
#  script self-elevates with a single UAC prompt.
# =========================================================================

$ErrorActionPreference = "SilentlyContinue"

# ---- Self-elevate -------------------------------------------------------
$cp = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $cp.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host ""
    Write-Host "Cleanup needs administrator rights. UAC prompt coming up..."
    $invokingUser = "$env:USERDOMAIN\$env:USERNAME"
    try {
        $sid = ([Security.Principal.NTAccount]$invokingUser).Translate(
            [Security.Principal.SecurityIdentifier]).Value
    } catch {
        $sid = ""
    }
    $thisScript = $MyInvocation.MyCommand.Definition
    try {
        Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", "`"$thisScript`"",
            "-OriginalUserSid", "`"$sid`""
        ) -Wait
    } catch {
        Write-Host "Elevation cancelled. Nothing was changed." -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
    }
    exit
}

# Parse passthrough arg
$scriptArgs = $args
$OriginalUserSid = ""
for ($i = 0; $i -lt $scriptArgs.Count - 1; $i++) {
    if ($scriptArgs[$i] -eq "-OriginalUserSid") {
        $OriginalUserSid = $scriptArgs[$i + 1]
    }
}

Write-Host ""
Write-Host "=========================================================="
Write-Host " DateClock cleanup"
Write-Host "=========================================================="
Write-Host ""

$Names = @("DateClock", "BigClock")
$report = @()

# ---- 1. Stop running processes ------------------------------------------
Write-Host "Stopping any running processes..."
foreach ($n in $Names) {
    Get-Process -Name $n -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "  Stopping $n (PID $($_.Id))"
        $_ | Stop-Process -Force
        $report += "Stopped $n PID $($_.Id)"
    }
}
Start-Sleep -Milliseconds 600

# ---- 2. Apps & Features registry entries (HKLM and HKCU) ----------------
Write-Host "Removing Apps & Features registry entries..."
foreach ($hive in @("HKLM:", "HKCU:")) {
    foreach ($n in $Names) {
        $key = "$hive\Software\Microsoft\Windows\CurrentVersion\Uninstall\$n"
        if (Test-Path $key) {
            Remove-Item -Path $key -Recurse -Force
            Write-Host "  Removed $key"
            $report += "Removed $key"
        }
    }
}

# ---- 3. Run-at-logon entries -------------------------------------------
Write-Host "Removing autostart entries..."

function Remove-RunEntry($hivePath, $label) {
    foreach ($n in $Names) {
        $val = Get-ItemProperty -Path $hivePath -Name $n -ErrorAction SilentlyContinue
        if ($val) {
            Remove-ItemProperty -Path $hivePath -Name $n -ErrorAction SilentlyContinue
            Write-Host "  Removed ${label}: $n"
            $script:report += "Removed $label $n autostart entry"
        }
    }
}

# Current admin's HKCU
Remove-RunEntry "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" "current admin HKCU"

# Original user's HKCU (we're admin now, so address it via HKEY_USERS\<SID>)
if ($OriginalUserSid) {
    $userRun = "Registry::HKEY_USERS\$OriginalUserSid\Software\Microsoft\Windows\CurrentVersion\Run"
    if (Test-Path "Registry::HKEY_USERS\$OriginalUserSid") {
        Remove-RunEntry $userRun "user HKCU"
    }
}

# Sweep all loaded user hives just in case
Get-ChildItem "Registry::HKEY_USERS" -ErrorAction SilentlyContinue | ForEach-Object {
    $sid = $_.PSChildName
    # Skip system SIDs and _Classes hives
    if ($sid -match "^S-1-5-21" -and $sid -notlike "*_Classes") {
        $path = "Registry::HKEY_USERS\$sid\Software\Microsoft\Windows\CurrentVersion\Run"
        if (Test-Path $path) {
            Remove-RunEntry $path "user-$sid"
        }
    }
}

# ---- 4. Shortcuts -------------------------------------------------------
Write-Host "Removing shortcuts..."
$shortcutLocations = @(
    (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs"),
    (Join-Path $env:PUBLIC "Desktop"),
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"),
    ([Environment]::GetFolderPath("Desktop"))
)
foreach ($loc in $shortcutLocations) {
    foreach ($n in $Names) {
        $lnk = Join-Path $loc "$n.lnk"
        if (Test-Path $lnk) {
            Remove-Item -Path $lnk -Force
            Write-Host "  Removed $lnk"
            $report += "Removed $lnk"
        }
    }
}

# ---- 5. Install folders -------------------------------------------------
Write-Host "Removing install folders if any remain..."
$installPaths = @(
    (Join-Path $env:ProgramFiles "DateClock"),
    (Join-Path $env:ProgramFiles "BigClock"),
    (Join-Path ${env:ProgramFiles(x86)} "DateClock"),
    (Join-Path ${env:ProgramFiles(x86)} "BigClock"),
    (Join-Path $env:LOCALAPPDATA "Programs\DateClock"),
    (Join-Path $env:LOCALAPPDATA "Programs\BigClock")
)
foreach ($p in $installPaths) {
    if ($p -and (Test-Path $p)) {
        try {
            Remove-Item -Path $p -Recurse -Force -ErrorAction Stop
            Write-Host "  Removed $p"
            $report += "Removed $p"
        } catch {
            Write-Host "  Could NOT remove $p ($($_.Exception.Message))" `
                -ForegroundColor Yellow
            $report += "FAILED to remove $p"
        }
    }
}

# ---- 6. User config ----------------------------------------------------
Write-Host ""
Write-Host "Your saved settings live in:"
$configPaths = @(
    (Join-Path $env:APPDATA "DateClock"),
    (Join-Path $env:APPDATA "BigClock")
)
$existingConfig = $configPaths | Where-Object { Test-Path $_ }
if ($existingConfig.Count -eq 0) {
    Write-Host "  (no config folders found)"
} else {
    foreach ($p in $existingConfig) { Write-Host "  $p" }
    Write-Host ""
    $ans = Read-Host "Delete these too? Keeping them lets a future reinstall remember your settings. [y/N]"
    if ($ans -match '^[Yy]') {
        foreach ($p in $existingConfig) {
            Remove-Item -Path $p -Recurse -Force
            Write-Host "  Removed $p"
            $report += "Removed $p"
        }
    } else {
        Write-Host "  Kept config folders."
    }
}

# ---- Summary -----------------------------------------------------------
Write-Host ""
Write-Host "=========================================================="
Write-Host " Cleanup summary"
Write-Host "=========================================================="
if ($report.Count -eq 0) {
    Write-Host "Nothing to clean up — DateClock was not registered on this PC."
} else {
    foreach ($line in $report) { Write-Host "  $line" }
}
Write-Host ""
Write-Host "Done. DateClock no longer appears in Settings -> Apps."
Write-Host ""
Read-Host "Press Enter to close"
