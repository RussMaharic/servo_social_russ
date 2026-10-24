# ==============================================================================
# t2-BOTS SDK — Zero-Dependency Windows PowerShell Bootstrap & Port Fixer
# Supported Platforms: Windows 10 & Windows 11 (x64 / ARM64)
# ==============================================================================

[CmdletBinding()]
param (
    [switch]$SkipOpenSSH = $false,
    [switch]$SkipVenv = $false
)

$ErrorActionPreference = "Stop"

Write-Host "===================================================================" -ForegroundColor Cyan
Write-Host "🚀 t2-BOTS Robotics SDK — Windows Platform Bootstrap & Port Setup" -ForegroundColor Cyan
Write-Host "===================================================================" -ForegroundColor Cyan

# 1. Check Python binary
$pyCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pyCmd = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pyCmd = "py -3"
} else {
    Write-Error "❌ Python 3 is not found on PATH. Please install Python 3.10+ from python.org or Microsoft Store."
    exit 1
}

$pyVer = & $pyCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
Write-Host "✔ Found Python: $pyCmd (version $pyVer)" -ForegroundColor Green

# 2. Check OpenSSH Client Capability
Write-Host "`n🔒 Checking OpenSSH Client for Headless Reverse Tunnels..." -ForegroundColor Cyan
$sshAvailable = Get-Command ssh -ErrorAction SilentlyContinue

if (-not $sshAvailable -and -not $SkipOpenSSH) {
    Write-Host "OpenSSH client not found. Checking Windows Optional Features..." -ForegroundColor Yellow
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($isAdmin) {
        Write-Host "Elevated session detected: Installing OpenSSH Client via DISM..." -ForegroundColor Yellow
        try {
            Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
            Write-Host "✔ OpenSSH Client successfully installed!" -ForegroundColor Green
        } catch {
            Write-Warning "Failed to install OpenSSH Client automatically: $_"
        }
    } else {
        Write-Warning "OpenSSH Client is missing. To enable automatic headless reverse tunnels, run PowerShell as Administrator:"
        Write-Warning "   Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0"
    }
} else {
    Write-Host "✔ OpenSSH Client is available on PATH." -ForegroundColor Green
}

# 3. Check Serial Drivers (CH343 / CH340 / CP210x / FTDI)
Write-Host "`n🔌 Scanning Windows COM Ports & Hardware Descriptors..." -ForegroundColor Cyan
$comPorts = Get-CimInstance -ClassName Win32_SerialPort -ErrorAction SilentlyContinue
if ($comPorts) {
    foreach ($p in $comPorts) {
        Write-Host "  • Found Device: $($p.DeviceID) - $($p.Description) (PNP ID: $($p.PNPDeviceID))" -ForegroundColor Gray
    }
} else {
    Write-Host "  (No active serial devices currently plugged in)" -ForegroundColor DarkGray
}

# 4. Virtual Environment & SDK Installation
$ScriptDir = if ($MyInvocation.MyCommand -and $MyInvocation.MyCommand.Path) { Split-Path -Parent $MyInvocation.MyCommand.Path } else { $null }
$RepoRoot = if ($ScriptDir -and (Test-Path (Join-Path $ScriptDir "..\dist"))) { Split-Path -Parent $ScriptDir } else { Join-Path $HOME ".t2-bots" }
if (-not (Test-Path $RepoRoot)) {
    New-Item -ItemType Directory -Path $RepoRoot -Force | Out-Null
}

if (-not $SkipVenv) {
    Write-Host "`n📦 Setting up Python Virtual Environment..." -ForegroundColor Cyan
    $venvPath = Join-Path $RepoRoot ".venv"
    if (-not (Test-Path $venvPath)) {
        Write-Host "Creating virtual environment at $venvPath..."
        & $pyCmd -m venv $venvPath
    }

    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    $venvPip = Join-Path $venvPath "Scripts\pip.exe"

    Write-Host "Upgrading pip, setuptools, wheel..." -ForegroundColor Gray
    & $venvPython -m pip install --upgrade pip setuptools wheel

    # Prefer this checkout's source, including the browser companion.
    if (Test-Path (Join-Path $RepoRoot 'pyproject.toml')) {
        & $venvPython -m pip install -e "${RepoRoot}[gateway]"
        if ($LASTEXITCODE -ne 0) { throw 'Source installation failed.' }
        Write-Host 'Open the browser workspace with: t2-connect' -ForegroundColor Green
        return
    }
    # Install a current release, never silently substitute the legacy wheel.
    $localWheel = Get-ChildItem -Path (Join-Path $RepoRoot "dist\t2_bots-0.3.1-*.whl") -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($localWheel) {
        Write-Host "Installing local distribution wheel: $($localWheel.FullName)..." -ForegroundColor Cyan
        & $venvPip install "$($localWheel.FullName)[gateway]"
    } else {
        Write-Host "Downloading and installing latest t2-bots universal release wheel..." -ForegroundColor Cyan
        $releaseUrl = "https://github.com/RussMaharic/servo_social_russ/releases/download/v0.3.1/t2_bots-0.3.1-py3-none-any.whl"
        & $venvPip install "t2-bots[gateway] @ ${releaseUrl}"
    }
    if ($LASTEXITCODE -ne 0) { throw 'The v0.3.1 release could not be installed. Use the source launcher until a release is published.' }

    Write-Host "`n===================================================================" -ForegroundColor Green
    Write-Host "🎉 Windows Bootstrap Complete! To activate and run:" -ForegroundColor Green
    Write-Host "   .venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "   t2-bots detect" -ForegroundColor Yellow
    Write-Host "   t2-bots qualify-arm --arm auto" -ForegroundColor Yellow
    Write-Host "===================================================================" -ForegroundColor Green
}
