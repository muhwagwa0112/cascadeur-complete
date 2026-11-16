[CmdletBinding()]
param([Parameter(Mandatory)] [string] $TransactionManifest)

$ErrorActionPreference = 'Stop'
# Internal transaction child: the source installer or the Inno Setup parent
# must retain the sibling maintenance lease through this entire rollback. Do
# not acquire it again here: the non-inheritable parent handle deliberately
# excludes this child as well as every other installer/runtime reader.
. (Join-Path $PSScriptRoot 'upgrade-state.ps1')
if (-not (Test-Path -LiteralPath $TransactionManifest)) {
    throw "Installation transaction manifest is missing: $TransactionManifest"
}
$manifest = Get-Content -LiteralPath $TransactionManifest -Raw | ConvertFrom-Json
if ($manifest.schema -ne 2 -or $manifest.runtime_mode -ne 'code-in-place') {
    throw 'This restore requires a schema-2 code-in-place transaction; legacy whole-root backups must not replace authenticated state.'
}
$backupRoot = [IO.Path]::GetFullPath([string]$manifest.backup_root)
$allowedRoot = [IO.Path]::GetFullPath((Join-Path (Get-CascadeurLocalAppData) 'CascadeurMCP\backups'))
if (-not $backupRoot.StartsWith($allowedRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to restore from an unexpected backup root: $backupRoot"
}

$expectedRuntime = Join-Path (Get-CascadeurLocalAppData) 'CascadeurMCP\cascadeur-complete'
$expectedTargets = @{
    runtime = $expectedRuntime
    bridge = Join-Path (Get-CascadeurLocalAppData) 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete'
    events = Join-Path (Get-CascadeurLocalAppData) 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete_events'
}
foreach ($name in @('runtime', 'bridge', 'events')) {
    if ([IO.Path]::GetFullPath([string]$manifest.targets.$name.path) -ine [IO.Path]::GetFullPath($expectedTargets[$name])) {
        throw "Unexpected rollback target: $name"
    }
}
$expectedSettings = Join-Path (Get-CascadeurLocalAppData) 'Nekki Limited\Cascadeur\settings.json'
$expectedCodex = Join-Path $env:USERPROFILE '.codex\config.toml'
if ([IO.Path]::GetFullPath([string]$manifest.cascadeur_settings.path) -ine [IO.Path]::GetFullPath($expectedSettings) -or
    [IO.Path]::GetFullPath([string]$manifest.codex_config.path) -ine [IO.Path]::GetFullPath($expectedCodex)) {
    throw 'Unexpected configuration rollback target.'
}
$rollbackFailures = [System.Collections.Generic.List[string]]::new()
try { Restore-CascadeurRuntimeCode $manifest.targets.runtime $backupRoot }
catch { $rollbackFailures.Add($_.Exception.Message) }

foreach ($name in @('bridge', 'events')) {
    try {
    $entry = $manifest.targets.$name
    $target = [IO.Path]::GetFullPath([string]$entry.path)
    if ($entry.existed) {
        $source = Join-Path $backupRoot $name
        if (-not (Test-Path -LiteralPath $source)) { throw "Backup target is missing: $source" }
    }
    if (Test-Path -LiteralPath $target) {
        Get-CascadeurInstallIdentity $target | Out-Null
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    if ($entry.existed) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
    }
    } catch { $rollbackFailures.Add($_.Exception.Message) }
}

foreach ($item in @(
    [pscustomobject]@{ Entry = $manifest.cascadeur_settings; Backup = 'cascadeur-settings.json' },
    [pscustomobject]@{ Entry = $manifest.codex_config; Backup = 'codex-config.toml' }
)) {
    try {
    $target = [IO.Path]::GetFullPath([string]$item.Entry.path)
    if ($item.Entry.existed) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $backupRoot $item.Backup) -Destination $target -Force
    } elseif (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Force
    }
    } catch { $rollbackFailures.Add($_.Exception.Message) }
}

if ($rollbackFailures.Count) {
    throw "Installation rollback incomplete; retain ${backupRoot}. $($rollbackFailures -join '; ')"
}

Write-Output "Restored installation state from $backupRoot"
