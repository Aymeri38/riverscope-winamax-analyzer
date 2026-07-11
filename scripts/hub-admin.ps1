[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $ProjectRoot ".runtime\python\python.exe"

try {
    $WinamaxProcesses = @(
        Get-Process -ErrorAction Stop |
            Where-Object { $_.ProcessName -ieq "Winamax" }
    )
}
catch {
    [Console]::Error.WriteLine("Administration refusee : impossible de verifier si Winamax.exe est actif.")
    exit 23
}
if ($WinamaxProcesses.Count -gt 0) {
    [Console]::Error.WriteLine("Winamax.exe est actif : administration du hub refusee.")
    exit 23
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Runtime Python local absent. Executez d'abord .\install.ps1."
}
if ($env:WXA_COMMUNITY_APPROVAL_ACK -cne "YES" -or
    [string]::IsNullOrWhiteSpace($env:WXA_COMMUNITY_APPROVAL_REFERENCE)) {
    [Console]::Error.WriteLine("Definissez WXA_COMMUNITY_APPROVAL_ACK=YES et WXA_COMMUNITY_APPROVAL_REFERENCE.")
    exit 2
}
if (-not $env:WXA_HUB_DATA_DIR) {
    $env:WXA_HUB_DATA_DIR = Join-Path $ProjectRoot "hub-data"
}
elseif (-not [System.IO.Path]::IsPathRooted($env:WXA_HUB_DATA_DIR)) {
    $env:WXA_HUB_DATA_DIR = Join-Path $ProjectRoot $env:WXA_HUB_DATA_DIR
}
$env:PYTHONPATH = Join-Path $ProjectRoot "backend"

& $Python -m app.community_hub.cli @CommandArgs
exit $LASTEXITCODE
