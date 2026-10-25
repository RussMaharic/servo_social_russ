$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $projectRoot 'dexops\scripts\start-connect.ps1') @args
exit $LASTEXITCODE
