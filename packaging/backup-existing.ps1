[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $RuntimeRoot,
    [Parameter(Mandatory)] [string] $BridgeRoot,
    [Parameter(Mandatory)] [string] $EventsRoot,
    [Parameter(Mandatory)] [string] $TransactionManifest
)

$ErrorActionPreference = 'Stop'
$backupRoot = Join-Path $env:LOCALAPPDATA ('CascadeurMCP\backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-pre-upgrade')
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
$runtimeOwnership = Join-Path $RuntimeRoot 'state\install-ownership.json'
if ((Test-Path -LiteralPath $RuntimeRoot) -and -not (Test-Path -LiteralPath $runtimeOwnership)) {
    throw 'An unmanaged Cascadeur MCP runtime already exists at the install target. Back it up and remove it before installing.'
}
$targets = [ordered]@{ runtime = $RuntimeRoot; bridge = $BridgeRoot; events = $EventsRoot }
$targetState = [ordered]@{}
foreach ($entry in $targets.GetEnumerator()) {
    $source = [IO.Path]::GetFullPath([string]$entry.Value)
    $exists = Test-Path -LiteralPath $source
    $targetState[$entry.Key] = [pscustomobject]@{ path = $source; existed = $exists }
    if ($exists) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $backupRoot $entry.Key) -Recurse -Force
    }
}
$settings = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\settings.json'
$settingsExisted = Test-Path -LiteralPath $settings
if ($settingsExisted) {
    Copy-Item -LiteralPath $settings -Destination (Join-Path $backupRoot 'cascadeur-settings.json')
}
$codexConfig = Join-Path $env:USERPROFILE '.codex\config.toml'
$codexExisted = Test-Path -LiteralPath $codexConfig
if ($codexExisted) {
    Copy-Item -LiteralPath $codexConfig -Destination (Join-Path $backupRoot 'codex-config.toml')
}
$manifest = [ordered]@{
    schema = 1
    backup_root = $backupRoot
    targets = $targetState
    cascadeur_settings = [pscustomobject]@{ path = $settings; existed = $settingsExisted }
    codex_config = [pscustomobject]@{ path = $codexConfig; existed = $codexExisted }
}
New-Item -ItemType Directory -Path (Split-Path -Parent $TransactionManifest) -Force | Out-Null
$manifest | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $TransactionManifest -Encoding utf8
Write-Output $backupRoot
