[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$RuntimeRoot = Join-Path $env:LOCALAPPDATA 'CascadeurMCP\cascadeur-complete'
$BridgeRoot = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete'
$EventsRoot = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\user_scripts\cascadeur_complete_events'
$BackupRoot = Join-Path $env:LOCALAPPDATA ('CascadeurMCP\backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-cascadeur-complete')
$CodexConfig = Join-Path $env:USERPROFILE '.codex\config.toml'
$CascadeurSettings = Join-Path $env:LOCALAPPDATA 'Nekki Limited\Cascadeur\settings.json'

New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
New-Item -ItemType Directory -Path $BridgeRoot -Force | Out-Null
New-Item -ItemType Directory -Path $EventsRoot -Force | Out-Null
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

if (Test-Path -LiteralPath $CodexConfig) {
    Copy-Item -LiteralPath $CodexConfig -Destination (Join-Path $BackupRoot 'codex-config.toml')
}
if (Test-Path -LiteralPath $CascadeurSettings) {
    Copy-Item -LiteralPath $CascadeurSettings -Destination (Join-Path $BackupRoot 'cascadeur-settings.json')
    $Settings = Get-Content -LiteralPath $CascadeurSettings -Raw | ConvertFrom-Json
    if ($Settings.Python.Commands -notcontains 'cascadeur_complete') {
        $Settings.Python.Commands += 'cascadeur_complete'
    }
    if ($Settings.Python.Events -notcontains 'cascadeur_complete_events') {
        $Settings.Python.Events += 'cascadeur_complete_events'
    }
    $Settings | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $CascadeurSettings -Encoding utf8
}

foreach ($Name in @('pyproject.toml', 'uv.lock', 'README.md', 'policy.default.json')) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot $Name) -Destination (Join-Path $RuntimeRoot $Name) -Force
}
foreach ($Directory in @('src', 'inventory')) {
    $Destination = Join-Path $RuntimeRoot $Directory
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Copy-Item -Path (Join-Path $ProjectRoot ($Directory + '\*')) -Destination $Destination -Recurse -Force
}
Copy-Item -Path (Join-Path $ProjectRoot 'cascadeur_side\cascadeur_complete\*') -Destination $BridgeRoot -Recurse -Force
Copy-Item -Path (Join-Path $ProjectRoot 'cascadeur_side\cascadeur_complete_events\*') -Destination $EventsRoot -Recurse -Force

$Policy = Join-Path $RuntimeRoot 'policy.json'
if (-not (Test-Path -LiteralPath $Policy)) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'policy.default.json') -Destination $Policy
}

Push-Location $RuntimeRoot
try {
    uv sync --frozen
} finally {
    Pop-Location
}

$Executable = Join-Path $RuntimeRoot '.venv\Scripts\cascadeur-complete.exe'
if (-not (Test-Path -LiteralPath $Executable)) {
    throw "MCP executable was not installed: $Executable"
}

$Existing = codex mcp list | Select-String -SimpleMatch 'cascadeur-complete'
if ($Existing) {
    codex mcp remove cascadeur-complete | Out-Null
}
codex mcp add cascadeur-complete -- $Executable | Out-Null

[pscustomobject]@{
    Runtime = $RuntimeRoot
    Bridge = $BridgeRoot
    Events = $EventsRoot
    Executable = $Executable
    Backup = $BackupRoot
    PoppetPreserved = (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'CascadeurMCP\poppet'))
} | ConvertTo-Json
