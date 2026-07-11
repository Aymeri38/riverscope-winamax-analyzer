$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $ProjectRoot '.runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Exécutez install.ps1 avant ce script.' }
Push-Location (Join-Path $ProjectRoot 'backend')
try {
    $env:PYTHONPATH = Join-Path $ProjectRoot 'backend'
    $env:WXA_DISABLE_WATCHER = '1'
    & $Python -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Les tests ont échoué.' }
}
finally { Pop-Location }

