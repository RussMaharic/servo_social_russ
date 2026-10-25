$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonCommand = Get-Command py, python -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $pythonCommand) { throw 'Install Python 3.10+ from python.org, then reopen this launcher.' }
& $pythonCommand.Source (Join-Path $projectRoot 'scripts\setup-dexops.py') @args
if ($LASTEXITCODE -ne 0) { throw 'Dexops setup failed. Read the message above before retrying.' }
