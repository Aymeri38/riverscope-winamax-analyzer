[CmdletBinding()]
param(
    [string]$BindHost = $(if ($env:WXA_HUB_HOST) { $env:WXA_HUB_HOST } else { "127.0.0.1" }),
    [int]$Port = $(if ($env:WXA_HUB_PORT) { [int]$env:WXA_HUB_PORT } else { 8040 }),
    [string]$DataDir = $env:WXA_HUB_DATA_DIR,
    [string]$SslCertFile = $env:WXA_HUB_TLS_CERT,
    [string]$SslKeyFile = $env:WXA_HUB_TLS_KEY
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".runtime\python\python.exe"

try {
    $WinamaxProcesses = @(
        Get-Process -ErrorAction Stop |
            Where-Object { $_.ProcessName -ieq "Winamax" }
    )
}
catch {
    [Console]::Error.WriteLine("Hub refuse : impossible de verifier si Winamax.exe est actif.")
    exit 23
}
if ($WinamaxProcesses.Count -gt 0) {
    [Console]::Error.WriteLine("Winamax.exe est actif : hub refuse, aucune relance automatique.")
    exit 23
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Runtime Python local absent. Executez d'abord .\install.ps1."
}
if ($env:WXA_COMMUNITY_APPROVAL_ACK -cne "YES" -or
    [string]::IsNullOrWhiteSpace($env:WXA_COMMUNITY_APPROVAL_REFERENCE)) {
    [Console]::Error.WriteLine("Definissez WXA_COMMUNITY_APPROVAL_ACK=YES et WXA_COMMUNITY_APPROVAL_REFERENCE avant le lancement.")
    exit 2
}

if ([string]::IsNullOrWhiteSpace($DataDir)) {
    $DataDir = Join-Path $ProjectRoot "hub-data"
}
elseif (-not [System.IO.Path]::IsPathRooted($DataDir)) {
    $DataDir = Join-Path $ProjectRoot $DataDir
}
$env:WXA_HUB_DATA_DIR = [System.IO.Path]::GetFullPath($DataDir)
$env:WXA_HUB_HOST = $BindHost
$env:WXA_HUB_PORT = [string]$Port
$env:PYTHONPATH = Join-Path $ProjectRoot "backend"

$Arguments = @("-m", "app.community_hub.runner", "--host", $BindHost, "--port", [string]$Port)
if (-not [string]::IsNullOrWhiteSpace($SslCertFile)) {
    $Arguments += @("--ssl-certfile", $SslCertFile)
}
if (-not [string]::IsNullOrWhiteSpace($SslKeyFile)) {
    $Arguments += @("--ssl-keyfile", $SslKeyFile)
}

& $Python @Arguments
exit $LASTEXITCODE
