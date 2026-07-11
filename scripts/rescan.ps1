$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $ProjectRoot '.runtime\python\python.exe'
$SafetyExitCode = 23

try {
    $WinamaxProcesses = @(
        Get-Process -ErrorAction Stop |
            Where-Object { $_.ProcessName -ieq 'Winamax' }
    )
}
catch {
    Write-Host 'Rescannage refusé : impossible de confirmer que Winamax.exe est absent.' -ForegroundColor Red
    exit $SafetyExitCode
}

if ($WinamaxProcesses.Count -gt 0) {
    Write-Host "Rescannage refusé : Winamax.exe est en cours d’exécution." -ForegroundColor Red
    exit $SafetyExitCode
}

if (-not (Test-Path -LiteralPath $Python)) { throw 'Exécutez install.ps1 avant ce script.' }
$env:PYTHONPATH = Join-Path $ProjectRoot 'backend'
$env:WXA_DATA_DIR = Join-Path $ProjectRoot 'data'
Push-Location (Join-Path $ProjectRoot 'backend')
$ExitCode = 1
try {
    & $Python -m app.cli rescan
    $ExitCode = $LASTEXITCODE
}
finally { Pop-Location }

exit $ExitCode
