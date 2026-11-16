[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $RuntimeRoot,
    [Parameter(Mandatory)] [string] $TransactionManifest,
    [switch] $SkipCodexRegistration
)

$ErrorActionPreference = 'Stop'
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
. (Join-Path $PSScriptRoot 'upgrade-state.ps1')
$InstallLocalAppData = Get-CascadeurLocalAppData
Assert-CascadeurUpgradeIdle $RuntimeRoot
# Both installers keep the runtime root, persistent directories and policy in place.
# Their schema-2 transaction restores code and installer ownership on failure. Never
# merge a historical backup here: it can resurrect deleted tokens/claims or
# conflict with newer state. Backups are for explicit transaction rollback only.
$SettingsPath = Join-Path $InstallLocalAppData 'Nekki Limited\Cascadeur\settings.json'
$UserScriptsRoot = [IO.Path]::GetFullPath((Join-Path $InstallLocalAppData 'Nekki Limited\Cascadeur\user_scripts')).TrimEnd('\')
$CodexConfig = Join-Path $env:USERPROFILE '.codex\config.toml'
if (-not (Test-Path -LiteralPath $TransactionManifest -PathType Leaf)) { throw 'An installer transaction manifest is required before hook effects.' }
$IncomingTransaction = Get-Content -LiteralPath $TransactionManifest -Raw | ConvertFrom-Json
Assert-CascadeurInstallerTransaction $IncomingTransaction
if ([IO.Path]::GetFullPath([string]$IncomingTransaction.targets.runtime.path) -ine $RuntimeRoot) { throw 'Install hooks runtime differs from its transaction.' }
Assert-CascadeurRuntimeIdentity $IncomingTransaction.targets.runtime
Read-CascadeurInstallerEffects $IncomingTransaction | Out-Null
$BackupRoot = [string]$IncomingTransaction.backup_root

$StateRoot = Join-Path $RuntimeRoot 'state'
New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
$OwnershipPath = Join-Path $StateRoot 'install-ownership.json'
$OwnershipExisted = Test-Path -LiteralPath $OwnershipPath
$ExistingOwnership = if ($OwnershipExisted) {
    Get-Content -LiteralPath $OwnershipPath -Raw | ConvertFrom-Json
} else { $null }
$ActiveOwnership = $OwnershipExisted -and (
    $null -eq $ExistingOwnership.installed -or [bool]$ExistingOwnership.installed
)
$NeedsTransactionMigration = $ActiveOwnership -and $IncomingTransaction -and -not $ExistingOwnership.transaction_manifest
$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name

try {
Start-CascadeurInstallerEffect $IncomingTransaction 'state_acl'
& icacls.exe $StateRoot /inheritance:r /grant:r "${CurrentIdentity}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
$aclExitCode = $LASTEXITCODE
Complete-CascadeurInstallerEffect $IncomingTransaction 'state_acl'
if ($aclExitCode -ne 0) { throw 'Unable to restrict the MCP state directory ACL' }

if (Test-Path -LiteralPath $SettingsPath) {
    $settings = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
} else {
    New-Item -ItemType Directory -Path (Split-Path -Parent $SettingsPath) -Force | Out-Null
    $settings = [pscustomobject]@{
        Python = [pscustomobject]@{ Commands = @('commands'); Events = @('events') }
    }
}
    if ($null -eq $settings.PSObject.Properties['Python']) {
        $settings | Add-Member -NotePropertyName Python -NotePropertyValue ([pscustomobject]@{})
    }
    if ($null -eq $settings.Python.PSObject.Properties['Commands']) {
        $settings.Python | Add-Member -NotePropertyName Commands -NotePropertyValue @('commands')
    }
    if ($null -eq $settings.Python.PSObject.Properties['Events']) {
        # An omitted Events setting uses Cascadeur's vendor event dispatchers.
        # Making it explicit must retain scene_idle/event_message and friends.
        $settings.Python | Add-Member -NotePropertyName Events -NotePropertyValue @('events')
    } elseif ($ActiveOwnership -and -not $ExistingOwnership.event_preexisting -and
        @($settings.Python.Events).Count -eq 1 -and
        @($settings.Python.Events)[0] -eq 'cascadeur_complete_events') {
        # Repair installs made by the earlier hooks with only our empty event
        # package. Preserve any explicit custom event configuration unchanged.
        $settings.Python.Events = @('events', 'cascadeur_complete_events')
    }
    if ($null -eq $settings.Python.PSObject.Properties['Path']) {
        $settings.Python | Add-Member -NotePropertyName Path -NotePropertyValue @()
    }
    $commandPreexisting = @($settings.Python.Commands) -contains 'cascadeur_complete'
    $eventPreexisting = @($settings.Python.Events) -contains 'cascadeur_complete_events'
    $settings.Python.Commands = @($settings.Python.Commands | Where-Object { $_ -ne 'cascadeur_complete' }) + 'cascadeur_complete'
    $settings.Python.Events = @($settings.Python.Events | Where-Object { $_ -ne 'cascadeur_complete_events' }) + 'cascadeur_complete_events'
    # Cascadeur resolves Commands/Events entries by module name only and does
    # not put user_scripts on sys.path itself; without this entry both bridge
    # packages fail to import at startup.
    $pathPreexisting = @($settings.Python.Path | Where-Object {
        $_ -and ([IO.Path]::GetFullPath([string]$_).TrimEnd('\') -ieq $UserScriptsRoot)
    }).Count -gt 0
    if (-not $pathPreexisting) {
        $settings.Python.Path = @($settings.Python.Path) + $UserScriptsRoot
    }
    $temporary = "$SettingsPath.cascadeur-mcp.tmp"
    Start-CascadeurInstallerEffect $IncomingTransaction 'cascadeur_settings'
    $settings | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $SettingsPath -Force
    Complete-CascadeurInstallerEffect $IncomingTransaction 'cascadeur_settings'

$previousCodex = $null
# A skipped registration never owns a Codex change or needs its preimage.
# Even a read of an absent registration leaves native exit code 1 behind.
if (-not $SkipCodexRegistration -and (Get-Command codex -ErrorAction SilentlyContinue)) {
    try { $previousCodex = (& codex mcp get cascadeur-complete --json 2>$null | ConvertFrom-Json) } catch {}
}
if (-not $ActiveOwnership) {
    Start-CascadeurInstallerEffect $IncomingTransaction 'ownership'
    [ordered]@{
        schema = 2
        installed = $true
        command_preexisting = [bool]$commandPreexisting
        event_preexisting = [bool]$eventPreexisting
        path_preexisting = [bool]$pathPreexisting
        user_scripts_path = $UserScriptsRoot
        codex_preexisting = $previousCodex
        codex_registered_by_installer = $false
        transaction_manifest = $IncomingTransaction
    } | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OwnershipPath -Encoding utf8
    Complete-CascadeurInstallerEffect $IncomingTransaction 'ownership'
} elseif ($NeedsTransactionMigration) {
    # Source installs created before schema 2 have no uninstall transaction.
    # Preserve their original settings/Codex ownership while adopting the
    # current installer's pre-upgrade bridge/runtime baseline.
    if ($null -eq $ExistingOwnership.schema) {
        $ExistingOwnership | Add-Member -NotePropertyName schema -NotePropertyValue 2
    } else {
        $ExistingOwnership.schema = 2
    }
    if ($null -eq $ExistingOwnership.installed) {
        $ExistingOwnership | Add-Member -NotePropertyName installed -NotePropertyValue $true
    } else {
        $ExistingOwnership.installed = $true
    }
    if ($null -eq $ExistingOwnership.PSObject.Properties['transaction_manifest']) {
        $ExistingOwnership | Add-Member -NotePropertyName transaction_manifest -NotePropertyValue $IncomingTransaction
    } else {
        $ExistingOwnership.transaction_manifest = $IncomingTransaction
    }
    Start-CascadeurInstallerEffect $IncomingTransaction 'ownership'
    $ExistingOwnership | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OwnershipPath -Encoding utf8
    Complete-CascadeurInstallerEffect $IncomingTransaction 'ownership'
}

# Upgrades over an ownership record that predates the Python.Path entry adopt
# the state observed before this run, so uninstall only removes what we added.
$ownership = Get-Content -LiteralPath $OwnershipPath -Raw | ConvertFrom-Json
if ($null -eq $ownership.PSObject.Properties['path_preexisting']) {
    $ownership | Add-Member -NotePropertyName path_preexisting -NotePropertyValue ([bool]$pathPreexisting)
    $ownership | Add-Member -NotePropertyName user_scripts_path -NotePropertyValue $UserScriptsRoot -Force
    Start-CascadeurInstallerEffect $IncomingTransaction 'ownership'
    $ownership | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OwnershipPath -Encoding utf8
    Complete-CascadeurInstallerEffect $IncomingTransaction 'ownership'
}

$codexRegistered = $false
if (-not $SkipCodexRegistration -and (Get-Command codex -ErrorAction SilentlyContinue)) {
    $executable = Join-Path $RuntimeRoot 'cascadeur-complete.exe'
    if (-not (Test-Path -LiteralPath $executable)) {
        $executable = Join-Path $RuntimeRoot '.venv\Scripts\cascadeur-complete.exe'
    }
    if (-not (Test-Path -LiteralPath $executable)) { throw "Missing installed MCP executable under: $RuntimeRoot" }
    if ($previousCodex -and -not $ActiveOwnership) {
        throw 'A pre-existing Codex MCP named cascadeur-complete is already registered. Remove or rename it before installing.'
    }
    Start-CascadeurInstallerEffect $IncomingTransaction 'codex_config'
    & codex mcp remove cascadeur-complete 2>$null | Out-Null
    Complete-CascadeurInstallerEffect $IncomingTransaction 'codex_config'
    Start-CascadeurInstallerEffect $IncomingTransaction 'codex_config'
    & codex mcp add cascadeur-complete -- $executable | Out-Null
    $codexExitCode = $LASTEXITCODE
    Complete-CascadeurInstallerEffect $IncomingTransaction 'codex_config'
    if ($codexExitCode -ne 0) { throw 'Codex MCP registration failed' }
    $codexRegistered = $true
    $ownership = Get-Content -LiteralPath $OwnershipPath -Raw | ConvertFrom-Json
    if ($null -eq $ownership.codex_registered_by_installer) {
        $ownership | Add-Member -NotePropertyName codex_registered_by_installer -NotePropertyValue $true
    } else {
        $ownership.codex_registered_by_installer = $true
    }
    Start-CascadeurInstallerEffect $IncomingTransaction 'ownership'
    $ownership | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OwnershipPath -Encoding utf8
    Complete-CascadeurInstallerEffect $IncomingTransaction 'ownership'
}
Assert-CascadeurRuntimeIdentity $IncomingTransaction.targets.runtime
} catch {
    $hookFailure = $_
    try {
        Restore-CascadeurInstallerMetadata $IncomingTransaction
    } catch {
        throw "Install hooks failed: $($hookFailure.Exception.Message). Metadata rollback incomplete; retain ${BackupRoot}. $($_.Exception.Message)"
    }
    throw $hookFailure
}

[pscustomobject]@{ Runtime = $RuntimeRoot; Backup = $BackupRoot; CodexRegistered = $codexRegistered } |
    ConvertTo-Json -Compress
