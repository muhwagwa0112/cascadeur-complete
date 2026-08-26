[CmdletBinding()]
param(
    [string] $RuntimeRoot = (Join-Path $env:LOCALAPPDATA 'CascadeurMCP\cascadeur-complete'),
    [switch] $RequireSignature,
    [switch] $SkipCascadeurVersion
)

$ErrorActionPreference = 'Stop'
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$FrozenExecutable = Join-Path $RuntimeRoot 'cascadeur-complete.exe'
$SourceExecutable = Join-Path $RuntimeRoot '.venv\Scripts\cascadeur-complete.exe'
$Executable = if (Test-Path -LiteralPath $FrozenExecutable) { $FrozenExecutable } else { $SourceExecutable }
$BridgeRoot = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete'
$EventsRoot = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete_events'
$CascadeurExecutable = if ($env:CASCADEUR_EXE) { $env:CASCADEUR_EXE } else { 'C:\Program Files\Cascadeur\cascadeur.exe' }

$checks = [ordered]@{
    RuntimeExists = Test-Path -LiteralPath $RuntimeRoot
    ExecutableExists = Test-Path -LiteralPath $Executable
    BridgeRuntimeExists = Test-Path -LiteralPath (Join-Path $BridgeRoot 'runtime.py')
    BridgeCommandExists = Test-Path -LiteralPath (Join-Path $BridgeRoot 'process_pending.py')
    BridgeEventsExist = Test-Path -LiteralPath $EventsRoot
    CascadeurInstalled = Test-Path -LiteralPath $CascadeurExecutable
    CascadeurVersion = $null
    CascadeurVersionExact = $false
    SignatureStatus = $null
    CodexAvailable = [bool](Get-Command codex -ErrorAction SilentlyContinue)
    CodexRegistered = $false
    CodexRegisteredPath = $null
    CascadeurCommandRegistered = $false
    CascadeurEventRegistered = $false
    McpSmoke = $false
}

if ($checks.CascadeurInstalled) {
    $checks.CascadeurVersion = (Get-Item -LiteralPath $CascadeurExecutable).VersionInfo.ProductVersion
    $checks.CascadeurVersionExact = [string]$checks.CascadeurVersion -eq '2026.1.2.0.15343'
}
if ($checks.ExecutableExists) {
    $checks.SignatureStatus = [string](Get-AuthenticodeSignature -LiteralPath $Executable).Status
}
$settingsPath = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\settings.json'
if (Test-Path -LiteralPath $settingsPath) {
    $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    $checks.CascadeurCommandRegistered = @($settings.Python.Commands) -contains 'cascadeur_complete'
    $checks.CascadeurEventRegistered = @($settings.Python.Events) -contains 'cascadeur_complete_events'
}
if ($checks.CodexAvailable) {
    try {
        $registration = (& codex mcp get cascadeur-complete --json 2>$null | ConvertFrom-Json)
        $checks.CodexRegisteredPath = [string]$registration.transport.command
        $checks.CodexRegistered = (
            $registration.enabled -and
            ([IO.Path]::GetFullPath($checks.CodexRegisteredPath) -eq [IO.Path]::GetFullPath($Executable))
        )
    } catch {
        $checks.CodexRegistered = $false
    }
}

$required = @(
    'RuntimeExists', 'ExecutableExists', 'BridgeRuntimeExists', 'BridgeCommandExists',
    'BridgeEventsExist', 'CascadeurCommandRegistered', 'CascadeurEventRegistered'
)
if (-not $SkipCascadeurVersion) { $required += @('CascadeurInstalled', 'CascadeurVersionExact') }
if ($checks.CodexAvailable) { $required += 'CodexRegistered' }
if ($RequireSignature) {
    if ($checks.SignatureStatus -ne 'Valid') { $required += 'SignatureValid' }
    $checks.SignatureValid = $checks.SignatureStatus -eq 'Valid'
}

if (-not ($required | Where-Object { -not $checks[$_] })) {
    $SmokeExecutable = if ($checks.CodexAvailable) { $checks.CodexRegisteredPath } else { $Executable }
    $smokeOutput = & $Executable --smoke --server $SmokeExecutable --timeout 30 2>&1
    $checks.McpSmoke = $LASTEXITCODE -eq 0
    $checks.McpSmokeResult = ($smokeOutput -join "`n")
}
$required += 'McpSmoke'

$checks | ConvertTo-Json -Depth 10
if ($required | Where-Object { -not $checks[$_] }) { exit 1 }
