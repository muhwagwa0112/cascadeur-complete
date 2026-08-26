[CmdletBinding()]
param([switch] $SkipCodexRegistration)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$RuntimeRoot = Join-Path $env:LOCALAPPDATA 'CascadeurMCP\cascadeur-complete'
$BridgeRoot = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete'
$EventsRoot = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete_events'
$BackupRoot = Join-Path $env:LOCALAPPDATA ('CascadeurMCP\backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-source-install')
$StagingRoot = Join-Path $env:LOCALAPPDATA ('CascadeurMCP\staging\' + [guid]::NewGuid().ToString('N'))
$StageRuntime = Join-Path $StagingRoot 'runtime'
$StageBridge = Join-Path $StagingRoot 'bridge'
$StageEvents = Join-Path $StagingRoot 'events'
$TransactionManifest = Join-Path $BackupRoot 'transaction.json'

foreach ($target in @($RuntimeRoot, $BridgeRoot, $EventsRoot, $BackupRoot, $StagingRoot)) {
    $full = [IO.Path]::GetFullPath($target)
    if (-not $full.StartsWith([IO.Path]::GetFullPath($env:LOCALAPPDATA) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to install outside Local AppData: $full"
    }
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv is required for a source install' }

# Windows cannot atomically replace a Python environment while a registered
# stdio server is still running from it. Fail before staging work and preserve
# the active installation; the caller can close Codex and retry.
$activeRuntimeProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ExecutablePath -and [IO.Path]::GetFullPath([string]$_.ExecutablePath).StartsWith(
        $RuntimeRoot + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}
if ($activeRuntimeProcesses) {
    $processIds = ($activeRuntimeProcesses | Select-Object -ExpandProperty ProcessId) -join ', '
    throw "Cascadeur MCP is running from the install target (PIDs: $processIds). Close Codex, then retry the source install."
}

New-Item -ItemType Directory -Path $StageRuntime, $StageBridge, $StageEvents, $BackupRoot -Force | Out-Null
foreach ($name in @('pyproject.toml', 'uv.lock', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'policy.default.json')) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $name) -Destination $StageRuntime
}
foreach ($directory in @('src', 'inventory')) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $directory) -Destination $StageRuntime -Recurse
}
Copy-Item -Path (Join-Path $ProjectRoot 'cascadeur_side\cascadeur_complete\*') -Destination $StageBridge -Recurse -Force
Copy-Item -Path (Join-Path $ProjectRoot 'cascadeur_side\cascadeur_complete_events\*') -Destination $StageEvents -Recurse -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'policy.default.json') -Destination (Join-Path $StageRuntime 'policy.json')

Push-Location $StageRuntime
try {
    & uv sync --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Staged dependency installation failed' }
} finally {
    Pop-Location
}
$Executable = Join-Path $StageRuntime '.venv\Scripts\cascadeur-complete.exe'
if (-not (Test-Path -LiteralPath $Executable)) { throw "Staged MCP executable is missing: $Executable" }
$previousSmokeRoot = $env:CASCADEUR_MCP_ROOT
$env:CASCADEUR_MCP_ROOT = Join-Path $StagingRoot 'smoke-state'
& uv run --project $StageRuntime python (Join-Path $ProjectRoot 'scripts\mcp-smoke.py') --server $Executable --timeout 30
if ($null -eq $previousSmokeRoot) { Remove-Item Env:CASCADEUR_MCP_ROOT -ErrorAction SilentlyContinue }
else { $env:CASCADEUR_MCP_ROOT = $previousSmokeRoot }
if ($LASTEXITCODE -ne 0) { throw 'Staged MCP smoke failed' }
# Windows virtual environments and their console-script launchers are not
# relocatable. Keep the staged smoke as a dependency/installability check, but
# recreate the environment after the runtime directory reaches its final path.
Remove-Item -LiteralPath (Join-Path $StageRuntime '.venv') -Recurse -Force

$movedOld = [System.Collections.Generic.List[object]]::new()
$activatedTargets = [System.Collections.Generic.List[string]]::new()
$targetState = [ordered]@{}
try {
    foreach ($pair in @(
        [pscustomobject]@{ Target = $RuntimeRoot; Stage = $StageRuntime; BackupName = 'runtime' },
        [pscustomobject]@{ Target = $BridgeRoot; Stage = $StageBridge; BackupName = 'bridge' },
        [pscustomobject]@{ Target = $EventsRoot; Stage = $StageEvents; BackupName = 'events' }
    )) {
        $targetState[$pair.BackupName] = [pscustomobject]@{
            path = [IO.Path]::GetFullPath($pair.Target)
            existed = [bool](Test-Path -LiteralPath $pair.Target)
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $pair.Target) -Force | Out-Null
        if (Test-Path -LiteralPath $pair.Target) {
            $backup = Join-Path $BackupRoot $pair.BackupName
            Move-Item -LiteralPath $pair.Target -Destination $backup
            $movedOld.Add([pscustomobject]@{ Target = $pair.Target; Backup = $backup })
        }
        Move-Item -LiteralPath $pair.Stage -Destination $pair.Target
        $activatedTargets.Add($pair.Target)
    }

    [ordered]@{
        schema = 1
        backup_root = $BackupRoot
        targets = $targetState
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $TransactionManifest -Encoding utf8

    # Preserve the ownership baseline across source upgrades. The old runtime
    # was moved atomically into the transaction backup above.
    $PreviousOwnership = Join-Path $BackupRoot 'runtime\state\install-ownership.json'
    if (Test-Path -LiteralPath $PreviousOwnership) {
        $NewStateRoot = Join-Path $RuntimeRoot 'state'
        New-Item -ItemType Directory -Path $NewStateRoot -Force | Out-Null
        Copy-Item -LiteralPath $PreviousOwnership -Destination (Join-Path $NewStateRoot 'install-ownership.json') -Force
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
    foreach ($target in $activatedTargets) {
        if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
    }
    foreach ($item in $movedOld) {
        if (Test-Path -LiteralPath $item.Backup) { Move-Item -LiteralPath $item.Backup -Destination $item.Target }
    }
    throw
} finally {
    if (Test-Path -LiteralPath $StagingRoot) { Remove-Item -LiteralPath $StagingRoot -Recurse -Force }
}

[pscustomobject]@{
    Runtime = $RuntimeRoot
    Bridge = $BridgeRoot
    Events = $EventsRoot
    Executable = Join-Path $RuntimeRoot '.venv\Scripts\cascadeur-complete.exe'
    Backup = $BackupRoot
} | ConvertTo-Json
