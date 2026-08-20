[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$RuntimeRoot = Join-Path $env:LOCALAPPDATA 'CascadeurMCP\cascadeur-complete'
$BridgeRoot = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete'
$Executable = Join-Path $RuntimeRoot '.venv\Scripts\cascadeur-complete.exe'
$Registry = Join-Path $RuntimeRoot 'state\feature_registry.json'

$Checks = [ordered]@{
    RuntimeExists = Test-Path -LiteralPath $RuntimeRoot
    ExecutableExists = Test-Path -LiteralPath $Executable
    BridgeRuntimeExists = Test-Path -LiteralPath (Join-Path $BridgeRoot 'runtime.py')
    BridgeCommandExists = Test-Path -LiteralPath (Join-Path $BridgeRoot 'process_pending.py')
    RegistryExists = Test-Path -LiteralPath $Registry
    CodexRegistered = [bool](codex mcp list | Select-String -SimpleMatch 'cascadeur-complete')
    PoppetPreserved = [bool](codex mcp list | Select-String -Pattern '^poppet\s')
}

if ($Checks.Values -contains $false) {
    $Checks | ConvertTo-Json
    exit 1
}

$Manifest = Get-Content -LiteralPath $Registry -Raw | ConvertFrom-Json
$Checks.FeatureCount = $Manifest.feature_count
$Checks.UnclassifiedCount = $Manifest.unclassified_count
if ($Manifest.schema_version -ne 2) {
    throw "Unexpected feature registry schema version: $($Manifest.schema_version)"
}
if ($Manifest.unclassified_count -ne 0) {
    throw "Feature registry contains $($Manifest.unclassified_count) unclassified or untested rows"
}
$Checks | ConvertTo-Json
