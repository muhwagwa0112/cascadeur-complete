[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $RuntimeRoot,
    [Parameter(Mandatory)] [string] $BridgeRoot,
    [Parameter(Mandatory)] [string] $EventsRoot,
    [Parameter(Mandatory)] [string] $TransactionManifest
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'upgrade-state.ps1')
$InstallLocalAppData = Get-CascadeurLocalAppData
Assert-CascadeurUpgradeIdle $RuntimeRoot
$backupRoot = Join-Path $InstallLocalAppData ('CascadeurMCP\backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-pre-upgrade')
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
$runtimeOwnership = Join-Path $RuntimeRoot 'state\install-ownership.json'
if ((Test-Path -LiteralPath $RuntimeRoot) -and -not (Test-Path -LiteralPath $runtimeOwnership)) {
    throw 'An unmanaged Cascadeur MCP runtime already exists at the install target. Back it up and remove it before installing.'
}
$targets = [ordered]@{ bridge = $BridgeRoot; events = $EventsRoot }
$targetState = [ordered]@{ runtime = (Backup-CascadeurRuntimeCode $RuntimeRoot $backupRoot) }
foreach ($entry in $targets.GetEnumerator()) {
    $source = [IO.Path]::GetFullPath([string]$entry.Value)
    $exists = Test-Path -LiteralPath $source
    $targetState[$entry.Key] = [pscustomobject]@{ path = $source; existed = $exists }
    if ($exists) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $backupRoot $entry.Key) -Recurse -Force
    }
}
$configurationState = Backup-CascadeurInstallerConfiguration $backupRoot
$manifest = [ordered]@{
    schema = 2
    runtime_mode = 'code-in-place'
    backup_root = $backupRoot
    targets = $targetState
    cascadeur_settings = $configurationState.cascadeur_settings
    codex_config = $configurationState.codex_config
}
New-Item -ItemType Directory -Path (Split-Path -Parent $TransactionManifest) -Force | Out-Null
Write-CascadeurInstallerJson $TransactionManifest $manifest
Write-Output $backupRoot
