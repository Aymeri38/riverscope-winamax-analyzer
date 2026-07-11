[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ResolvedSource = (Resolve-Path -LiteralPath $SourcePath).Path
$Pem = Get-Content -LiteralPath $ResolvedSource -Raw -Encoding utf8

if ($Pem -match 'PRIVATE KEY') {
    throw 'Le fichier contient une clé privée et ne doit jamais être installé sur un PC membre.'
}
if ($Pem -notmatch '-----BEGIN CERTIFICATE-----' -or
    $Pem -notmatch '-----END CERTIFICATE-----') {
    throw 'Le fichier ne contient pas de certificat PEM valide.'
}

# certutil is present on supported Windows versions and validates the public
# certificate without importing it into a Windows certificate store.
& certutil.exe -dump $ResolvedSource *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'Le certificat PEM est illisible ou mal formé.'
}

$DataDir = Join-Path $ProjectRoot 'data'
New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
$Destination = Join-Path $DataDir 'community-ca.crt'
Copy-Item -LiteralPath $ResolvedSource -Destination $Destination -Force
Write-Host "Autorité communautaire installée dans le projet : $Destination" -ForegroundColor Green
Write-Host "Aucun magasin de certificats Windows n’a été modifié."
