#Requires -Version 5.1
<#
.SYNOPSIS
    One-line installer for Valt.

    irm https://raw.githubusercontent.com/Stellar5055/Valt/main/install.ps1 | iex

    Re-running it updates an existing install.
    Scoop users are routed through scoop (so scoop update valt keeps working);
    everyone else gets a standalone install to %LOCALAPPDATA%\Valt.

    Standalone uninstall:  & ([scriptblock]::Create((irm <this url>))) -Uninstall
#>
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$repoBase = 'https://github.com/Stellar5055/Valt/releases/latest/download'
$manifestUrl = 'https://raw.githubusercontent.com/Stellar5055/Valt/main/bucket/valt.json'

if ($Uninstall) {
    # removes the standalone install; scoop users: scoop uninstall valt
    $dir = Join-Path $env:LOCALAPPDATA 'Valt'
    Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $fixed = ($userPath -split ';' | Where-Object { $_ -and $_ -ne $dir }) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $fixed, 'User')
    $programs = [Environment]::GetFolderPath('Programs')
    Remove-Item "$programs\Valt.lnk", "$programs\Valt CLI.lnk" -Force -ErrorAction SilentlyContinue
    Write-Host 'Valt removed.'
    return
}

if (Get-Command scoop -ErrorAction SilentlyContinue) {
    Write-Host 'Scoop detected - installing through scoop...'
    # install on a fresh machine; the update right after handles re-runs
    scoop install $manifestUrl
    scoop update valt
    return
}

# ---- standalone install (no scoop needed) ----
Write-Host 'Downloading Valt...'
$zip = Join-Path $env:TEMP 'valt.zip'
Invoke-WebRequest "$repoBase/valt.zip" -OutFile $zip -UseBasicParsing

$sums = (Invoke-WebRequest "$repoBase/SHA256SUMS.txt" -UseBasicParsing).Content
$line = ($sums -split "`r?`n") | Where-Object { $_ -match 'valt\.zip' }
if (-not $line -or $line -notmatch '([a-fA-F0-9]{64})') {
    throw 'Could not read the expected hash from SHA256SUMS.txt.'
}
$actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $Matches[1].ToLower()) {
    throw "Hash mismatch - download corrupted. Expected $($Matches[1]), got $actual."
}

$dir = Join-Path $env:LOCALAPPDATA 'Valt'
Expand-Archive $zip -DestinationPath $dir -Force

# put valt + valt-cli on the user PATH
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (($userPath -split ';') -notcontains $dir) {
    [Environment]::SetEnvironmentVariable('Path', "$($userPath.TrimEnd(';'));$dir", 'User')
}

# Start-menu shortcuts
$ws = New-Object -ComObject WScript.Shell
$programs = [Environment]::GetFolderPath('Programs')
$lnk = $ws.CreateShortcut("$programs\Valt.lnk");     $lnk.TargetPath = "$dir\valt.exe";     $lnk.Save()
$lnk = $ws.CreateShortcut("$programs\Valt CLI.lnk"); $lnk.TargetPath = "$dir\valt-cli.exe"; $lnk.Save()

Write-Host 'Valt installed. Open a NEW terminal and run valt, or find it in the Start menu.'
