[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$RuntimeRoot = Join-Path $env:LOCALAPPDATA 'CascadeurMCP\cascadeur-complete'
$BridgeRoot = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete'
$Executable = Join-Path $RuntimeRoot '.venv\Scripts\cascadeur-complete.exe'
$Registry = Join-Path $RuntimeRoot 'state\feature_registry.json'

$checks = [ordered]@{
    RuntimeExists = Test-Path -LiteralPath $RuntimeRoot
    ExecutableExists = Test-Path -LiteralPath $Executable
    BridgeRuntimeExists = Test-Path -LiteralPath (Join-Path $BridgeRoot 'runtime.py')
    BridgeCommandExists = Test-Path -LiteralPath (Join-Path $BridgeRoot 'process_pending.py')
    RegistryExists = Test-Path -LiteralPath $Registry
    CodexAvailable = [bool](Get-Command codex -ErrorAction SilentlyContinue)
    CodexRegistered = $false
    McpSmoke = $false
}
if ($checks.CodexAvailable) {
    $checks.CodexRegistered = [bool](& codex mcp list 2>$null | Select-String -SimpleMatch 'cascadeur-complete')
}
$required = @('RuntimeExists', 'ExecutableExists', 'BridgeRuntimeExists', 'BridgeCommandExists')
if ($checks.CodexAvailable) { $required += 'CodexRegistered' }
if (-not ($required | Where-Object { -not $checks[$_] })) {
    $output = & (Join-Path $RuntimeRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'mcp-smoke.py') --server $Executable --timeout 30 2>&1
    $checks.McpSmoke = $LASTEXITCODE -eq 0
    $checks.McpSmokeResult = ($output -join "`n")
    $checks.RegistryExists = Test-Path -LiteralPath $Registry
}
$required += @('McpSmoke', 'RegistryExists')
if ($checks.RegistryExists) {
    $manifest = Get-Content -LiteralPath $Registry -Raw | ConvertFrom-Json
    $checks.FeatureCount = $manifest.feature_count
    $checks.UnclassifiedCount = $manifest.unclassified_count
    $checks.SchemaVersion = $manifest.schema_version
}
$checks | ConvertTo-Json -Depth 10
if ($required | Where-Object { -not $checks[$_] }) { exit 1 }
