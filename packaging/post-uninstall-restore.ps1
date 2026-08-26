[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $OwnershipPath,
    [Parameter(Mandatory)] [string] $RuntimeOwnershipPath
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $OwnershipPath)) { exit 0 }
$runtimeOwnershipFull = [IO.Path]::GetFullPath($RuntimeOwnershipPath)
$allowedRuntimeRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'CascadeurMCP\cascadeur-complete\state'))
if (-not $runtimeOwnershipFull.StartsWith($allowedRuntimeRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to update ownership outside the runtime state root: $runtimeOwnershipFull"
}
function Set-RuntimeOwnershipInactive {
    if (Test-Path -LiteralPath $RuntimeOwnershipPath) {
        $retained = Get-Content -LiteralPath $RuntimeOwnershipPath -Raw | ConvertFrom-Json
        if ($null -eq $retained.installed) {
            $retained | Add-Member -NotePropertyName installed -NotePropertyValue $false
        } else {
            $retained.installed = $false
        }
        $retained | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $RuntimeOwnershipPath -Encoding utf8
    }
}
$ownership = Get-Content -LiteralPath $OwnershipPath -Raw | ConvertFrom-Json
$transaction = $ownership.transaction_manifest
if (-not $transaction) {
    Set-RuntimeOwnershipInactive
    exit 0
}
$backupRoot = [IO.Path]::GetFullPath([string]$transaction.backup_root)
$allowedRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'CascadeurMCP\backups'))
if (-not $backupRoot.StartsWith($allowedRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to restore from unexpected backup root: $backupRoot"
}
$targets = [ordered]@{
    bridge = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete'
    events = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete_events'
}
foreach ($entry in $targets.GetEnumerator()) {
    if (Test-Path -LiteralPath $entry.Value) {
        Remove-Item -LiteralPath $entry.Value -Recurse -Force
    }
    if ($transaction.targets.($entry.Key).existed) {
        $source = Join-Path $backupRoot $entry.Key
        if (-not (Test-Path -LiteralPath $source)) { throw "Pre-install backup is missing: $source" }
        New-Item -ItemType Directory -Path (Split-Path -Parent $entry.Value) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $entry.Value -Recurse -Force
    }
}

# The runtime state directory is intentionally retained, but this ownership record
# describes one installation transaction. Mark it inactive so a later reinstall
# captures a fresh baseline instead of restoring an older installation's backup.
Set-RuntimeOwnershipInactive
