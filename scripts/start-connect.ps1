$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimePath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtimePath)) {
    $pythonCommand = Get-Command py, python -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $pythonCommand) { throw 'Python 3.10 or newer is required for this source launcher. Use the standalone Windows download if available.' }
    & $pythonCommand.Source -c "import sys; assert sys.version_info >= (3,10), 'Python 3.10+ required'"
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.10 or newer, then reopen this launcher.' }
    & $pythonCommand.Source -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the project virtual environment.' }
}
& $runtimePath -m pip install -e "$projectRoot[gateway]"
if ($LASTEXITCODE -ne 0) { throw 'Installation failed. Check your internet connection and try again.' }
$commandDir = Join-Path $HOME '.local\bin'
New-Item -ItemType Directory -Path $commandDir -Force | Out-Null
$commandPath = Join-Path $commandDir 'dexops.cmd'
$command = "@echo off`r`n`"$runtimePath`" -m t2_bots.connect.app --workspace-url `"https://servosocialruss.vercel.app/`" %*`r`n"
[System.IO.File]::WriteAllText($commandPath, $command)
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$pathParts = @($userPath -split ';' | Where-Object { $_ })
if ($commandDir -notin $pathParts) {
    [Environment]::SetEnvironmentVariable('Path', (($pathParts + $commandDir) -join ';'), 'User')
}
Write-Host 'Dexops companion is starting. The deployed workspace will open automatically.' -ForegroundColor Green
Write-Host 'Future terminals can start Dexops from any folder by running: dexops' -ForegroundColor Green
& $runtimePath -m t2_bots.connect.app --workspace-url 'https://servosocialruss.vercel.app/'
if ($LASTEXITCODE -ne 0) { throw 'The companion could not start. Check whether port 4840 is already in use.' }
