[CmdletBinding()]
param([switch] $SkipCodexRegistration)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $ProjectRoot 'packaging\upgrade-state.ps1')
$InstallLocalAppData = Get-CascadeurLocalAppData
$RuntimeRoot = Join-Path $InstallLocalAppData 'CascadeurMCP\cascadeur-complete'
$BridgeRoot = Join-Path $InstallLocalAppData 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete'
$EventsRoot = Join-Path $InstallLocalAppData 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete_events'
$BackupRoot = Join-Path $InstallLocalAppData ('CascadeurMCP\backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-source-install')
$StagingRoot = Join-Path $InstallLocalAppData ('CascadeurMCP\staging\' + [guid]::NewGuid().ToString('N'))
$StageRuntime = Join-Path $StagingRoot 'runtime'
$StageBridge = Join-Path $StagingRoot 'bridge'
$StageEvents = Join-Path $StagingRoot 'events'
$TransactionManifest = Join-Path $BackupRoot 'transaction.json'

foreach ($target in @($RuntimeRoot, $BridgeRoot, $EventsRoot, $BackupRoot, $StagingRoot)) {
    $full = [IO.Path]::GetFullPath($target)
    if (-not $full.StartsWith([IO.Path]::GetFullPath($InstallLocalAppData) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to install outside Local AppData: $full"
    }
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv is required for a source install' }

Assert-CascadeurUpgradeIdle $RuntimeRoot

$movedOld = [System.Collections.Generic.List[object]]::new()
$activatedTargets = [System.Collections.Generic.List[string]]::new()
$targetState = [ordered]@{}
$maintenanceLease = $null
$runtimeState = $null
$runtimeActivationStarted = $false
try {
    New-Item -ItemType Directory -Path $StageRuntime, $StageBridge, $StageEvents, $BackupRoot -Force | Out-Null
    foreach ($name in @('pyproject.toml', 'uv.lock', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'policy.default.json')) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot $name) -Destination $StageRuntime
    }
    foreach ($directory in @('src', 'inventory')) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot $directory) -Destination $StageRuntime -Recurse
    }
    Copy-Item -Path (Join-Path $ProjectRoot 'cascadeur_side\cascadeur_complete\*') -Destination $StageBridge -Recurse -Force
    Copy-Item -Path (Join-Path $ProjectRoot 'cascadeur_side\cascadeur_complete_events\*') -Destination $StageEvents -Recurse -Force
    # Dependency preparation and both smoke calls use disposable state roots.
    # Existing authenticated state stays at its original physical runtime root.

    Push-Location $StageRuntime
    try {
        & uv sync --frozen
        if ($LASTEXITCODE -ne 0) { throw 'Staged dependency installation failed' }
        & uv run --frozen python -m cascadeur_complete.package_fingerprint --bridge-root $StageBridge --output (Join-Path $StageRuntime 'bridge-package.json')
        if ($LASTEXITCODE -ne 0) { throw 'Bridge package fingerprint failed' }
    } finally {
        Pop-Location
    }
    $Executable = Join-Path $StageRuntime '.venv\Scripts\cascadeur-complete.exe'
    if (-not (Test-Path -LiteralPath $Executable)) { throw "Staged MCP executable is missing: $Executable" }
    $previousSmokeRoot = $env:CASCADEUR_MCP_ROOT
    try {
        $env:CASCADEUR_MCP_ROOT = Join-Path $StagingRoot 'smoke-state'
        & uv run --project $StageRuntime python (Join-Path $ProjectRoot 'scripts\mcp-smoke.py') --server $Executable --timeout 30
        if ($LASTEXITCODE -ne 0) { throw 'Staged MCP smoke failed' }
    } finally {
        if ($null -eq $previousSmokeRoot) { Remove-Item Env:CASCADEUR_MCP_ROOT -ErrorAction SilentlyContinue }
        else { $env:CASCADEUR_MCP_ROOT = $previousSmokeRoot }
    }
    # Windows virtual environments and their console-script launchers are not
    # relocatable. Keep the staged smoke as a dependency/installability check, but
    # recreate the environment after the runtime directory reaches its final path.
    Remove-Item -LiteralPath (Join-Path $StageRuntime '.venv') -Recurse -Force

    # Hold the existing sibling lease across code activation, hooks and rollback.
    # Never move/delete the runtime root or its persistent directories.
    $maintenanceLease = Enter-CascadeurMaintenanceLease $RuntimeRoot
    Assert-CascadeurUpgradeIdle $RuntimeRoot
    $runtimeState = Backup-CascadeurRuntimeCode $RuntimeRoot $BackupRoot
    $targetState['runtime'] = $runtimeState
    foreach ($pair in @(
        [pscustomobject]@{ Target = $BridgeRoot; BackupName = 'bridge' },
        [pscustomobject]@{ Target = $EventsRoot; BackupName = 'events' }
    )) {
        $targetState[$pair.BackupName] = [pscustomobject]@{
            path = [IO.Path]::GetFullPath($pair.Target)
            existed = [bool](Test-Path -LiteralPath $pair.Target)
        }
    }
    [ordered]@{
        schema = 2
        runtime_mode = 'code-in-place'
        backup_root = $BackupRoot
        targets = $targetState
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $TransactionManifest -Encoding utf8

    $runtimeActivationStarted = $true
    Clear-CascadeurRuntimeCode $RuntimeRoot
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    foreach ($entry in @(Get-CascadeurRuntimeCodeEntries $StageRuntime)) {
        Move-Item -LiteralPath $entry.FullName -Destination $RuntimeRoot
    }
    if (-not (Test-Path -LiteralPath (Join-Path $RuntimeRoot 'policy.json'))) {
        Copy-Item -LiteralPath (Join-Path $RuntimeRoot 'policy.default.json') -Destination (Join-Path $RuntimeRoot 'policy.json')
    }
    Assert-CascadeurUpgradeIdle $RuntimeRoot
    foreach ($pair in @(
        [pscustomobject]@{ Target = $BridgeRoot; Stage = $StageBridge; BackupName = 'bridge' },
        [pscustomobject]@{ Target = $EventsRoot; Stage = $StageEvents; BackupName = 'events' }
    )) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $pair.Target) -Force | Out-Null
        if (Test-Path -LiteralPath $pair.Target) {
            $backup = Join-Path $BackupRoot $pair.BackupName
            Move-Item -LiteralPath $pair.Target -Destination $backup
            $movedOld.Add([pscustomobject]@{ Target = $pair.Target; Backup = $backup })
        }
        Move-Item -LiteralPath $pair.Stage -Destination $pair.Target
        $activatedTargets.Add($pair.Target)
    }

    & uv sync --project $RuntimeRoot --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Final-path dependency installation failed' }
    $FinalExecutable = Join-Path $RuntimeRoot '.venv\Scripts\cascadeur-complete.exe'
    if (-not (Test-Path -LiteralPath $FinalExecutable)) {
        throw "Final-path MCP executable is missing: $FinalExecutable"
    }
    $previousSmokeRoot = $env:CASCADEUR_MCP_ROOT
    try {
        $env:CASCADEUR_MCP_ROOT = Join-Path $StagingRoot 'activated-smoke-state'
        & uv run --project $RuntimeRoot python (Join-Path $ProjectRoot 'scripts\mcp-smoke.py') --server $FinalExecutable --timeout 30
        if ($LASTEXITCODE -ne 0) { throw 'Final-path MCP smoke failed' }
    } finally {
        if ($null -eq $previousSmokeRoot) { Remove-Item Env:CASCADEUR_MCP_ROOT -ErrorAction SilentlyContinue }
        else { $env:CASCADEUR_MCP_ROOT = $previousSmokeRoot }
    }
    & (Join-Path $ProjectRoot 'packaging\install-hooks.ps1') -RuntimeRoot $RuntimeRoot `
        -TransactionManifest $TransactionManifest -SkipCodexRegistration:$SkipCodexRegistration
} catch {
    $installFailure = $_
    $rollbackFailures = [System.Collections.Generic.List[string]]::new()
    foreach ($target in $activatedTargets) {
        try {
            if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
        } catch { $rollbackFailures.Add($_.Exception.Message) }
    }
    foreach ($item in $movedOld) {
        try {
            if (Test-Path -LiteralPath $item.Target) { throw "Rollback target is still occupied: $($item.Target)" }
            if (Test-Path -LiteralPath $item.Backup) { Move-Item -LiteralPath $item.Backup -Destination $item.Target }
            else { throw "Rollback backup is missing: $($item.Backup)" }
        } catch { $rollbackFailures.Add($_.Exception.Message) }
    }
    if ($runtimeActivationStarted) {
        try { Restore-CascadeurRuntimeCode $runtimeState $BackupRoot }
        catch { $rollbackFailures.Add($_.Exception.Message) }
    }
    if ($rollbackFailures.Count) {
        throw "Installation failed: $($installFailure.Exception.Message). Rollback incomplete; retain ${BackupRoot}. $($rollbackFailures -join '; ')"
    }
    throw $installFailure
} finally {
    try {
        if (Test-Path -LiteralPath $StagingRoot) { Remove-Item -LiteralPath $StagingRoot -Recurse -Force }
    } finally {
        if ($null -ne $maintenanceLease) { $maintenanceLease.Dispose() }
    }
}

[pscustomobject]@{
    Runtime = $RuntimeRoot
    Bridge = $BridgeRoot
    Events = $EventsRoot
    Executable = Join-Path $RuntimeRoot '.venv\Scripts\cascadeur-complete.exe'
    Backup = $BackupRoot
} | ConvertTo-Json
