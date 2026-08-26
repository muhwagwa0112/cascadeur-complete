[CmdletBinding()]
param([string] $RuntimeRoot = (Join-Path $env:LOCALAPPDATA 'CascadeurMCP\cascadeur-complete'))

$ErrorActionPreference = 'Continue'
$OwnershipPath = Join-Path $RuntimeRoot 'state\install-ownership.json'
$ownership = if (Test-Path -LiteralPath $OwnershipPath) {
    Get-Content -LiteralPath $OwnershipPath -Raw | ConvertFrom-Json
} else { $null }
if ($ownership.codex_registered_by_installer -and (Get-Command codex -ErrorAction SilentlyContinue)) {
    & codex mcp remove cascadeur-complete 2>$null | Out-Null
    $previous = $ownership.codex_preexisting
    if ($previous -and $previous.transport.type -eq 'stdio' -and $previous.transport.command) {
        $arguments = @('mcp', 'add', 'cascadeur-complete')
        foreach ($entry in @($previous.transport.env_vars)) {
            $arguments += @('--env', [string]$entry)
        }
        $arguments += '--'
        $arguments += [string]$previous.transport.command
        $arguments += @($previous.transport.args | ForEach-Object { [string]$_ })
        & codex @arguments | Out-Null
    }
}

$settingsPath = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\settings.json'
if (Test-Path -LiteralPath $settingsPath) {
    $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    if ($settings.Python.Commands -and -not [bool]$ownership.command_preexisting) {
        $settings.Python.Commands = @($settings.Python.Commands | Where-Object { $_ -ne 'cascadeur_complete' })
    }
    if ($settings.Python.Events -and -not [bool]$ownership.event_preexisting) {
        $settings.Python.Events = @($settings.Python.Events | Where-Object { $_ -ne 'cascadeur_complete_events' })
    }
    $temporary = "$settingsPath.cascadeur-mcp.tmp"
    $settings | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $settingsPath -Force
}
