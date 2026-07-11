param(
    [Parameter(Mandatory = $true)]
    [string]$HubUrl,
    [Parameter(Mandatory = $true)]
    [string]$DisplayName
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".runtime\python\python.exe"

try {
    $winamaxProcesses = @(
        Get-Process -ErrorAction Stop |
            Where-Object { $_.ProcessName -ieq 'Winamax' }
    )
}
catch {
    [Console]::Error.WriteLine("Appairage refusé : impossible de vérifier si Winamax.exe est absent.")
    exit 23
}

if ($winamaxProcesses.Count -gt 0) {
    [Console]::Error.WriteLine("Appairage refusé : fermez Winamax avant de continuer.")
    exit 23
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    [Console]::Error.WriteLine("Runtime Python introuvable. Exécutez install.ps1.")
    exit 1
}

$communityCa = Join-Path $projectRoot 'data\community-ca.crt'
if ([string]::IsNullOrWhiteSpace($env:WXA_COMMUNITY_CA_CERT) -and
    (Test-Path -LiteralPath $communityCa -PathType Leaf)) {
    $env:WXA_COMMUNITY_CA_CERT = $communityCa
}

Push-Location (Join-Path $projectRoot "backend")
try {
    & $python -m app.community_cli join --hub-url $HubUrl --display-name $DisplayName --consent --consent-version "2"
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
