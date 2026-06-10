# ==========================================================================
#  DateClock installer (per-machine, requires admin)
#
#  Installs DateClock into C:\Program Files\DateClock so every user on this
#  PC can launch it from the Start Menu. Registers in HKLM so the entry
#  in Settings -> Apps -> Installed apps is visible to all users.
#
#  Run by double-clicking Install.bat. The script self-elevates: you'll
#  see one UAC prompt, then everything happens in an admin console window.
# ==========================================================================

$ErrorActionPreference = "Stop"

# ------ App metadata -------------------------------------------------------
$AppName    = "DateClock"
$AppVersion = "1.0.0"
$Publisher  = "DateClock"

# ------ Helper: parse named args (we can't use param() because we need
#        code to run BEFORE elevation) ------------------------------------
$scriptArgs = $args
function Get-NamedArg([string]$name, [string]$default = "") {
    for ($i = 0; $i -lt $scriptArgs.Count - 1; $i++) {
        if ($scriptArgs[$i] -eq "-$name") { return $scriptArgs[$i + 1] }
    }
    return $default
}

# When self-elevating we pass these along so the elevated process knows
# which user originally launched the installer (so we can put the autostart
# entry in *their* HKCU instead of the Administrator account's hive).
$OriginalUserName  = Get-NamedArg "OriginalUserName"  ""
$OriginalUserSid   = Get-NamedArg "OriginalUserSid"   ""
$OriginalScriptDir = Get-NamedArg "OriginalScriptDir" ""

# ------ Self-elevate if not already admin ----------------------------------
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $currentPrincipal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host ""
    Write-Host "DateClock installer needs administrator rights to install to"
    Write-Host "C:\Program Files. Click 'Yes' on the UAC prompt that appears."
    Write-Host ""

    $invokingUser = "$env:USERDOMAIN\$env:USERNAME"
    try {
        $invokingSid = ([Security.Principal.NTAccount]$invokingUser).Translate(
            [Security.Principal.SecurityIdentifier]).Value
    } catch {
        $invokingSid = ""
    }

    $thisScript = $MyInvocation.MyCommand.Definition
    $thisDir = Split-Path -Parent $thisScript

    $argList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$thisScript`"",
        "-OriginalUserName",  "`"$invokingUser`"",
        "-OriginalUserSid",   "`"$invokingSid`"",
        "-OriginalScriptDir", "`"$thisDir`""
    )

    try {
        Start-Process -FilePath "powershell.exe" -Verb RunAs `
            -ArgumentList $argList -Wait
    } catch {
        Write-Host ""
        Write-Host "Installation cancelled (administrator rights required)." `
            -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
    }
    exit
}

# =========================================================================
#  From here on we are running as administrator.
# =========================================================================

# Use the *original* script directory if we were re-launched after elevation;
# otherwise use our own location.
if ([string]::IsNullOrWhiteSpace($OriginalScriptDir)) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
} else {
    $ScriptDir = $OriginalScriptDir
}

$SourceExe = Join-Path $ScriptDir "dist\DateClock.exe"

if (-not (Test-Path $SourceExe)) {
    Write-Host ""
    Write-Host "ERROR: dist\DateClock.exe was not found in:" -ForegroundColor Red
    Write-Host "  $ScriptDir"
    Write-Host "Run build.bat first to produce the executable."
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# ------ Paths --------------------------------------------------------------
$ProgFiles = $env:ProgramFiles
if ([string]::IsNullOrWhiteSpace($ProgFiles)) { $ProgFiles = "C:\Program Files" }

$InstallDir       = Join-Path $ProgFiles $AppName
$InstalledExe     = Join-Path $InstallDir "$AppName.exe"
$UninstallScript  = Join-Path $InstallDir "uninstall.ps1"
$IconPath         = $InstalledExe        # icon is embedded in the EXE

# All-users Start Menu (visible to every account on this machine)
$AllUsersStartMenu = Join-Path $env:ProgramData `
    "Microsoft\Windows\Start Menu\Programs"
$StartMenuShortcut = Join-Path $AllUsersStartMenu "$AppName.lnk"

# Public desktop (visible to every account)
$PublicDesktop  = Join-Path $env:PUBLIC "Desktop"
$DesktopShortcut = Join-Path $PublicDesktop "$AppName.lnk"

# Apps & Features registration is per-machine
$UninstallRegKey = "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppName"

Write-Host ""
Write-Host "=========================================================="
Write-Host " $AppName Installer (per-machine)"
Write-Host "=========================================================="
Write-Host ""
Write-Host "Source     : $ScriptDir"
Write-Host "Installing to: $InstallDir"
if ($OriginalUserName) {
    Write-Host "Launched by: $OriginalUserName"
}
Write-Host ""

# ------ Stop any running DateClock instances on this machine ----------------
Get-Process -Name $AppName -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Stopping running $AppName instance (PID $($_.Id))..."
    try {
        $_ | Stop-Process -Force -ErrorAction Stop
    } catch {
        Write-Host "  (could not stop PID $($_.Id): $($_.Exception.Message))" `
            -ForegroundColor Yellow
    }
    Start-Sleep -Milliseconds 500
}

# ------ Ask about options --------------------------------------------------
function Ask-YesNo($question, $default = "y") {
    $hint = if ($default -eq "y") { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $a = Read-Host "$question $hint"
        if ([string]::IsNullOrWhiteSpace($a)) { $a = $default }
        if ($a -match '^[Yy]') { return $true }
        if ($a -match '^[Nn]') { return $false }
    }
}

$WantDesktop = Ask-YesNo "Create a desktop shortcut for all users?" "y"
$WantStartup = Ask-YesNo "Start $AppName automatically when YOU log in?" "y"
$LaunchNow   = Ask-YesNo "Launch $AppName when installation finishes?" "y"

# ------ Copy files ---------------------------------------------------------
Write-Host ""
Write-Host "Copying files..."
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item -Path $SourceExe -Destination $InstalledExe -Force

# ------ Generate the uninstaller -------------------------------------------
# We write uninstall.ps1 directly with hardcoded paths so it doesn't have to
# self-elevate via $args parsing — and so it works exactly the same whether
# triggered from Apps & Features or run manually.
$UninstallScriptBody = @"
# Auto-generated by DateClock installer. Removes DateClock from this PC.
`$ErrorActionPreference = "SilentlyContinue"

# Self-elevate if not running as admin (uninstalling from Program Files
# requires it). Apps & Features normally elevates HKLM uninstalls
# automatically, so this branch usually only fires for manual runs.
`$cp = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
if (-not `$cp.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    `$me = `$PSCommandPath
    if (-not `$me) { `$me = `$MyInvocation.MyCommand.Definition }
    Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList @(
        "-NoProfile","-ExecutionPolicy","Bypass","-File","`"`$me`""
    ) -Wait
    exit
}

`$AppName            = "$AppName"
`$InstallDir         = "$InstallDir"
`$StartMenuShortcut  = "$StartMenuShortcut"
`$DesktopShortcut    = "$DesktopShortcut"
`$UninstallRegKey    = "$UninstallRegKey"

# Stop any running clock instance
Get-Process -Name `$AppName -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 600

# Shortcuts
Remove-Item `$StartMenuShortcut -Force -ErrorAction SilentlyContinue
Remove-Item `$DesktopShortcut   -Force -ErrorAction SilentlyContinue

# Apps & Features entry (HKLM)
Remove-Item -Path `$UninstallRegKey -Recurse -Force -ErrorAction SilentlyContinue

# Autostart entry — sweep every loaded user hive, since we don't know
# which user originally got the Run entry written to their HKCU.
`$runSubpath = "Software\Microsoft\Windows\CurrentVersion\Run"
Get-ChildItem "Registry::HKEY_USERS" -ErrorAction SilentlyContinue | ForEach-Object {
    `$sid = `$_.PSChildName
    if (`$sid -match "^S-1-5-21" -and `$sid -notlike "*_Classes") {
        `$path = "Registry::HKEY_USERS\`$sid\`$runSubpath"
        if (Test-Path `$path) {
            Remove-ItemProperty -Path `$path -Name `$AppName `
                -ErrorAction SilentlyContinue
        }
    }
}

# Delete the install folder. The uninstall.ps1 file is INSIDE that folder
# and is currently being executed, so we can't delete the directory from
# within this same process. Spawn a detached cmd that waits 3s for this
# script to exit, then nukes the directory.
`$ToDelete = `$InstallDir
if (Test-Path `$ToDelete) {
    Start-Process -WindowStyle Hidden cmd.exe -ArgumentList @(
        "/c", "timeout /t 3 /nobreak >nul & rmdir /s /q ```"`$ToDelete```""
    )
}

Write-Host "DateClock uninstalled."
"@

Set-Content -Path $UninstallScript -Value $UninstallScriptBody -Encoding UTF8
# Re-write without BOM. Windows PowerShell 5.1 writes UTF-8 *with* BOM when
# given `-Encoding UTF8`, which makes some PowerShell parsers choke on the
# first line of the script. Use raw byte output (UTF-8 without BOM) instead.
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($UninstallScript,
                                   $UninstallScriptBody, $utf8NoBom)
} catch {
    # If the rewrite fails for some reason, the Set-Content result above
    # at least produced a runnable file in most cases.
}

# ------ Shortcuts ----------------------------------------------------------
function New-Shortcut($Path, $Target, $Icon) {
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($Path)
    $sc.TargetPath = $Target
    $sc.WorkingDirectory = (Split-Path -Parent $Target)
    $sc.IconLocation = "$Icon,0"
    $sc.Save()
}

Write-Host "Creating Start Menu shortcut (all users)..."
New-Shortcut -Path $StartMenuShortcut -Target $InstalledExe -Icon $IconPath

if ($WantDesktop) {
    Write-Host "Creating desktop shortcut (all users)..."
    New-Shortcut -Path $DesktopShortcut -Target $InstalledExe -Icon $IconPath
}

# ------ Autostart entry (per-user, in the *invoking* user's HKCU) ----------
# Even though we're running as admin, the original user is who actually
# wants DateClock at logon. Write to their hive via HKEY_USERS + their SID.
if ($WantStartup) {
    Write-Host "Enabling start with Windows for $OriginalUserName..."
    $runValueData = "`"$InstalledExe`""

    $written = $false
    if ($OriginalUserSid -and (Test-Path "Registry::HKEY_USERS\$OriginalUserSid")) {
        $runPathHKU = "Registry::HKEY_USERS\$OriginalUserSid\Software\Microsoft\Windows\CurrentVersion\Run"
        try {
            if (-not (Test-Path $runPathHKU)) {
                New-Item -Path $runPathHKU -Force | Out-Null
            }
            Set-ItemProperty -Path $runPathHKU -Name $AppName -Value $runValueData
            $written = $true
        } catch {
            Write-Host "  (couldn't write to original user's hive: $_)" -ForegroundColor Yellow
        }
    }
    if (-not $written) {
        # Fall back to writing to the current (admin) user's HKCU so the
        # installer at least leaves *something* registered. If you ran the
        # installer directly as Administrator, autostart will apply to that
        # admin account.
        Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
            -Name $AppName -Value $runValueData
        Write-Host "  (wrote to current user's HKCU)"
    }
}

# ------ Apps & Features registration (per-machine, HKLM) -------------------
Write-Host "Registering with Windows (Apps & Features)..."
if (-not (Test-Path $UninstallRegKey)) {
    New-Item -Path $UninstallRegKey -Force | Out-Null
}

$UninstallCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$UninstallScript`""

Set-ItemProperty -Path $UninstallRegKey -Name "DisplayName"     -Value $AppName
Set-ItemProperty -Path $UninstallRegKey -Name "DisplayVersion"  -Value $AppVersion
Set-ItemProperty -Path $UninstallRegKey -Name "Publisher"       -Value $Publisher
Set-ItemProperty -Path $UninstallRegKey -Name "DisplayIcon"     -Value $IconPath
Set-ItemProperty -Path $UninstallRegKey -Name "InstallLocation" -Value $InstallDir
Set-ItemProperty -Path $UninstallRegKey -Name "UninstallString" -Value $UninstallCmd
Set-ItemProperty -Path $UninstallRegKey -Name "NoModify"        -Value 1 -Type DWord
Set-ItemProperty -Path $UninstallRegKey -Name "NoRepair"        -Value 1 -Type DWord
$sizeKB = [int]((Get-Item $InstalledExe).Length / 1024)
Set-ItemProperty -Path $UninstallRegKey -Name "EstimatedSize"   -Value $sizeKB -Type DWord

# ------ Launch -------------------------------------------------------------
Write-Host ""
Write-Host "Done. Installed to:" -ForegroundColor Green
Write-Host "  $InstalledExe"
Write-Host ""

if ($LaunchNow) {
    # Launch as the *invoking* (non-admin) user, not as the admin account
    # we're currently running as. Use explorer.exe as the launcher trick so
    # the child process inherits the regular user's token.
    Write-Host "Launching $AppName..."
    try {
        Start-Process -FilePath "explorer.exe" -ArgumentList "`"$InstalledExe`""
    } catch {
        Start-Process -FilePath $InstalledExe
    }
}

Write-Host ""
Read-Host "Press Enter to close"
