[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeRoot = Join-Path $ProjectRoot '.runtime'
$PythonRoot = Join-Path $RuntimeRoot 'python'
$PythonExe = Join-Path $PythonRoot 'python.exe'
$Downloads = Join-Path $RuntimeRoot 'downloads'
$PythonVersion = '3.12.10'

Write-Host 'Installation locale de Winamax Analyzer' -ForegroundColor Cyan
Write-Host "Projet : $ProjectRoot"

New-Item -ItemType Directory -Force -Path $RuntimeRoot, $PythonRoot, $Downloads, (Join-Path $ProjectRoot 'data') | Out-Null

if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Host "Téléchargement de Python $PythonVersion portable dans le projet..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $PythonZip = Join-Path $Downloads "python-$PythonVersion-embed-amd64.zip"
    $PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonZip -UseBasicParsing
    Expand-Archive -LiteralPath $PythonZip -DestinationPath $PythonRoot -Force

}

$PthFile = Get-ChildItem -LiteralPath $PythonRoot -Filter 'python*._pth' | Select-Object -First 1
if (-not $PthFile) { throw 'Fichier de configuration Python portable introuvable.' }
$PthContent = Get-Content -LiteralPath $PthFile.FullName
$PthContent = $PthContent -replace '^#import site$', 'import site'
if ($PthContent -notcontains 'Lib\site-packages') { $PthContent += 'Lib\site-packages' }
if ($PthContent -notcontains '..\..\backend') { $PthContent += '..\..\backend' }
Set-Content -LiteralPath $PthFile.FullName -Value $PthContent -Encoding ASCII

$PipPackage = Join-Path $PythonRoot 'Lib\site-packages\pip'
if (-not (Test-Path -LiteralPath $PipPackage)) {
    Write-Host 'Amorçage ou réparation de pip dans le runtime local...'
    $GetPip = Join-Path $Downloads 'get-pip.py'
    if (-not (Test-Path -LiteralPath $GetPip)) {
        Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $GetPip -UseBasicParsing
    }
    & $PythonExe $GetPip --no-warn-script-location
    if ($LASTEXITCODE -ne 0) { throw 'Échec de l’installation locale de pip.' }
}

Write-Host 'Installation des dépendances Python dans le runtime du projet...'
& $PythonExe -m pip install --disable-pip-version-check --no-warn-script-location -r (Join-Path $ProjectRoot 'backend\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Échec de l’installation des dépendances Python.' }

$Npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $Npm) { throw 'Node.js/npm est requis mais npm.cmd est introuvable.' }
Write-Host 'Installation et compilation du frontend...'
& $Npm --prefix (Join-Path $ProjectRoot 'frontend') install --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Échec de npm install.' }
& $Npm --prefix (Join-Path $ProjectRoot 'frontend') run build
if ($LASTEXITCODE -ne 0) { throw 'Échec de la compilation du frontend.' }

Write-Host 'Initialisation de la base SQLite locale...'
Push-Location (Join-Path $ProjectRoot 'backend')
try {
    $env:PYTHONPATH = (Join-Path $ProjectRoot 'backend')
    $env:WXA_DATA_DIR = (Join-Path $ProjectRoot 'data')
    & $PythonExe -m app.cli init
    if ($LASTEXITCODE -ne 0) { throw 'Échec de l’initialisation de la base.' }
}
finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Installation terminée.' -ForegroundColor Green
Write-Host 'Démarrage : powershell -ExecutionPolicy Bypass -File .\start.ps1'
Write-Host 'URL locale : http://127.0.0.1:8000'
