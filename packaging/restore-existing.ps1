[CmdletBinding()]
param([Parameter(Mandatory)] [string] $TransactionManifest)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $TransactionManifest)) {
    throw "Installation transaction manifest is missing: $TransactionManifest"
}
$manifest = Get-Content -LiteralPath $TransactionManifest -Raw | ConvertFrom-Json
$backupRoot = [IO.Path]::GetFullPath([string]$manifest.backup_root)
$allowedRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'CascadeurMCP\backups'))
if (-not $backupRoot.StartsWith($allowedRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to restore from an unexpected backup root: $backupRoot"
}

foreach ($name in @('runtime', 'bridge', 'events')) {
    $entry = $manifest.targets.$name
    $target = [IO.Path]::GetFullPath([string]$entry.path)
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    if ($entry.existed) {
        $source = Join-Path $backupRoot $name
        if (-not (Test-Path -LiteralPath $source)) { throw "Backup target is missing: $source" }
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
    }
}

foreach ($item in @(
    [pscustomobject]@{ Entry = $manifest.cascadeur_settings; Backup = 'cascadeur-settings.json' },
    [pscustomobject]@{ Entry = $manifest.codex_config; Backup = 'codex-config.toml' }
)) {
    $target = [IO.Path]::GetFullPath([string]$item.Entry.path)
    if ($item.Entry.existed) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $backupRoot $item.Backup) -Destination $target -Force
    } elseif (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Force
    }
}

Write-Output "Restored installation state from $backupRoot"
