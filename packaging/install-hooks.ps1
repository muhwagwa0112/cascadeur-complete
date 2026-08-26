[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $RuntimeRoot,
    [string] $TransactionManifest,
    [switch] $SkipCodexRegistration
)

$ErrorActionPreference = 'Stop'
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$BackupRoot = Join-Path $env:LOCALAPPDATA ('CascadeurMCP\backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-installer')
$SettingsPath = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\settings.json'
$CodexConfig = Join-Path $env:USERPROFILE '.codex\config.toml'
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

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
$IncomingTransaction = if ($TransactionManifest -and (Test-Path -LiteralPath $TransactionManifest)) {
    Get-Content -LiteralPath $TransactionManifest -Raw | ConvertFrom-Json
} else { $null }
$NeedsTransactionMigration = $ActiveOwnership -and $IncomingTransaction -and -not $ExistingOwnership.transaction_manifest
$CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls.exe $StateRoot /inheritance:r /grant:r "${CurrentIdentity}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Unable to restrict the MCP state directory ACL' }

try {
if (-not (Test-Path -LiteralPath $SettingsPath)) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $SettingsPath) -Force | Out-Null
    [pscustomobject]@{
        Python = [pscustomobject]@{ Commands = @(); Events = @() }
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $SettingsPath -Encoding utf8
}
if (Test-Path -LiteralPath $SettingsPath) {
    Copy-Item -LiteralPath $SettingsPath -Destination (Join-Path $BackupRoot 'cascadeur-settings.json')
    $settings = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
    if ($null -eq $settings.PSObject.Properties['Python']) {
        $settings | Add-Member -NotePropertyName Python -NotePropertyValue ([pscustomobject]@{})
    }
    if ($null -eq $settings.Python.PSObject.Properties['Commands']) {
        $settings.Python | Add-Member -NotePropertyName Commands -NotePropertyValue @()
    }
    if ($null -eq $settings.Python.PSObject.Properties['Events']) {
        $settings.Python | Add-Member -NotePropertyName Events -NotePropertyValue @()
    }
    $commandPreexisting = @($settings.Python.Commands) -contains 'cascadeur_complete'
    $eventPreexisting = @($settings.Python.Events) -contains 'cascadeur_complete_events'
    $settings.Python.Commands = @($settings.Python.Commands | Where-Object { $_ -ne 'cascadeur_complete' }) + 'cascadeur_complete'
    $settings.Python.Events = @($settings.Python.Events | Where-Object { $_ -ne 'cascadeur_complete_events' }) + 'cascadeur_complete_events'
    $temporary = "$SettingsPath.cascadeur-mcp.tmp"
    $settings | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $SettingsPath -Force
}

$previousCodex = $null
if (Get-Command codex -ErrorAction SilentlyContinue) {
    try { $previousCodex = (& codex mcp get cascadeur-complete --json 2>$null | ConvertFrom-Json) } catch {}
}
if (-not $ActiveOwnership) {
    [ordered]@{
        schema = 2
        installed = $true
        command_preexisting = [bool]$commandPreexisting
        event_preexisting = [bool]$eventPreexisting
        codex_preexisting = $previousCodex
        codex_registered_by_installer = $false
        transaction_manifest = $IncomingTransaction
    } | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OwnershipPath -Encoding utf8
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
    $ExistingOwnership.transaction_manifest = $IncomingTransaction
    $ExistingOwnership | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OwnershipPath -Encoding utf8
}

$codexRegistered = $false
if (-not $SkipCodexRegistration -and (Get-Command codex -ErrorAction SilentlyContinue)) {
    if (Test-Path -LiteralPath $CodexConfig) {
        Copy-Item -LiteralPath $CodexConfig -Destination (Join-Path $BackupRoot 'codex-config.toml')
    }
    $executable = Join-Path $RuntimeRoot 'cascadeur-complete.exe'
    if (-not (Test-Path -LiteralPath $executable)) {
        $executable = Join-Path $RuntimeRoot '.venv\Scripts\cascadeur-complete.exe'
    }
    if (-not (Test-Path -LiteralPath $executable)) { throw "Missing installed MCP executable under: $RuntimeRoot" }
    if ($previousCodex -and -not $ActiveOwnership) {
        throw 'A pre-existing Codex MCP named cascadeur-complete is already registered. Remove or rename it before installing.'
    }
    & codex mcp remove cascadeur-complete 2>$null | Out-Null
    & codex mcp add cascadeur-complete -- $executable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Codex MCP registration failed' }
    $codexRegistered = $true
    $ownership = Get-Content -LiteralPath $OwnershipPath -Raw | ConvertFrom-Json
    if ($null -eq $ownership.codex_registered_by_installer) {
        $ownership | Add-Member -NotePropertyName codex_registered_by_installer -NotePropertyValue $true
    } else {
        $ownership.codex_registered_by_installer = $true
    }
    $ownership | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OwnershipPath -Encoding utf8
}
} catch {
    if (Test-Path -LiteralPath (Join-Path $BackupRoot 'cascadeur-settings.json')) {
        Copy-Item -LiteralPath (Join-Path $BackupRoot 'cascadeur-settings.json') -Destination $SettingsPath -Force
    }
    if (Test-Path -LiteralPath (Join-Path $BackupRoot 'codex-config.toml')) {
        Copy-Item -LiteralPath (Join-Path $BackupRoot 'codex-config.toml') -Destination $CodexConfig -Force
    }
    throw
}

[pscustomobject]@{ Runtime = $RuntimeRoot; Backup = $BackupRoot; CodexRegistered = $codexRegistered } |
    ConvertTo-Json -Compress
