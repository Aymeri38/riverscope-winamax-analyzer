[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot '.runtime\python\python.exe'
$SafetyExitCode = 23

try {
    $WinamaxProcesses = @(
        Get-Process -ErrorAction Stop |
            Where-Object { $_.ProcessName -ieq 'Winamax' }
    )
}
catch {
    Write-Error 'Démarrage refusé : impossible de vérifier si Winamax.exe est actif. Par précaution, aucun composant ne sera lancé.'
    exit $SafetyExitCode
}

if ($WinamaxProcesses.Count -gt 0) {
    Write-Host 'Démarrage refusé : Winamax.exe est en cours d’exécution.' -ForegroundColor Red
    Write-Host 'Fermez Winamax, puis relancez manuellement start.ps1. Aucun redémarrage automatique ne sera tenté.' -ForegroundColor Yellow
    exit $SafetyExitCode
}

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw 'Runtime Python local absent. Exécutez d’abord : powershell -ExecutionPolicy Bypass -File .\install.ps1'
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'frontend\dist\index.html'))) {
    throw 'Frontend non compilé. Exécutez d’abord .\install.ps1.'
}

$env:PYTHONPATH = (Join-Path $ProjectRoot 'backend')
$env:WXA_DATA_DIR = (Join-Path $ProjectRoot 'data')
$env:WXA_PORT = [string]$Port

Write-Host 'Winamax Analyzer — analyse post-session uniquement' -ForegroundColor Cyan
Write-Host "URL : http://127.0.0.1:$Port"
Write-Host 'Arrêt : Ctrl+C'

Push-Location (Join-Path $ProjectRoot 'backend')
$BackendExitCode = 1
try {
    & $PythonExe -m app.runner --host 127.0.0.1 --port $Port
    $BackendExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($BackendExitCode -eq $SafetyExitCode) {
    Write-Host 'Arrêt de sécurité : Winamax.exe a été détecté. Watcher et backend arrêtés.' -ForegroundColor Red
    Write-Host 'Aucun redémarrage automatique. Fermez Winamax puis relancez manuellement start.ps1.' -ForegroundColor Yellow
}

exit $BackendExitCode
