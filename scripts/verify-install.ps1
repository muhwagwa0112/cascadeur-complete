[CmdletBinding()]
param(
    [string] $RuntimeRoot,
    [switch] $RequireSignature,
    [switch] $SkipCascadeurVersion
)

$ErrorActionPreference = 'Stop'
$UpgradeHelper = Join-Path $PSScriptRoot 'upgrade-state.ps1'
if (-not (Test-Path -LiteralPath $UpgradeHelper -PathType Leaf)) {
    $UpgradeHelper = Join-Path (Split-Path -Parent $PSScriptRoot) 'packaging\upgrade-state.ps1'
}
if (-not (Test-Path -LiteralPath $UpgradeHelper -PathType Leaf)) { throw 'Canonical upgrade-state.ps1 helper is missing.' }
. $UpgradeHelper
$InstallLocalAppData = Get-CascadeurLocalAppData
if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $InstallLocalAppData 'CascadeurMCP\cascadeur-complete' }
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$FrozenExecutable = Join-Path $RuntimeRoot 'cascadeur-complete.exe'
$SourceExecutable = Join-Path $RuntimeRoot '.venv\Scripts\cascadeur-complete.exe'
$Executable = if (Test-Path -LiteralPath $FrozenExecutable) { $FrozenExecutable } else { $SourceExecutable }
$UserScriptsRoot = [IO.Path]::GetFullPath((Join-Path $InstallLocalAppData 'Nekki Limited\Cascadeur\user_scripts')).TrimEnd('\')
$BridgeRoot = Join-Path $UserScriptsRoot 'cascadeur_complete'
$EventsRoot = Join-Path $UserScriptsRoot 'cascadeur_complete_events'
$BridgeManifestPath = Join-Path $RuntimeRoot 'bridge-package.json'
$CascadeurExecutable = if ($env:CASCADEUR_EXE) { $env:CASCADEUR_EXE } else { 'C:\Program Files\Cascadeur\cascadeur.exe' }
$PinnedCascadeurVersion = '2026.1.3.0.15619'

function ConvertTo-BridgeJsonString([string] $Value) {
    # package_fingerprint.digest uses ensure_ascii=False and compact JSON.
    $builder = [Text.StringBuilder]::new()
    [void]$builder.Append('"')
    foreach ($character in $Value.ToCharArray()) {
        $number = [int]$character
        switch ($number) {
            8 { [void]$builder.Append('\b') }
            9 { [void]$builder.Append('\t') }
            10 { [void]$builder.Append('\n') }
            12 { [void]$builder.Append('\f') }
            13 { [void]$builder.Append('\r') }
            34 { [void]$builder.Append('\"') }
            92 { [void]$builder.Append('\\') }
            default {
                if ($number -lt 32) { [void]$builder.Append(('\u{0:x4}' -f $number)) }
                else { [void]$builder.Append($character) }
            }
        }
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Get-BridgeFilesFingerprint($Files) {
    $names = [string[]]@($Files.Keys)
    # Python sorts Unicode code points. Sorting UTF-32 hex sort keys also
    # handles supplementary characters without relying on locale or casing.
    $names = @($names | Sort-Object -Property @{ Expression = {
        $bytes = [Text.UTF32Encoding]::new($true, $false, $true).GetBytes($_)
        [BitConverter]::ToString($bytes).Replace('-', '')
    } })
    $builder = [Text.StringBuilder]::new()
    [void]$builder.Append('{')
    $separator = ''
    foreach ($name in $names) {
        [void]$builder.Append($separator)
        [void]$builder.Append((ConvertTo-BridgeJsonString $name))
        [void]$builder.Append(':')
        [void]$builder.Append((ConvertTo-BridgeJsonString $Files[$name]))
        $separator = ','
    }
    [void]$builder.Append('}')
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.UTF8Encoding]::new($false, $true).GetBytes($builder.ToString())
        return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '').ToLowerInvariant()
    } finally { $sha.Dispose() }
}

$checks = [ordered]@{
    LocalAppData = $InstallLocalAppData
    RuntimeRoot = $RuntimeRoot
    BridgeRoot = $BridgeRoot
    EventsRoot = $EventsRoot
    BridgeManifestPath = $BridgeManifestPath
    BridgeManifestScope = 'cascadeur_complete Python bytes; event package import files checked for presence'
    RuntimeExists = Test-Path -LiteralPath $RuntimeRoot
    ExecutableExists = Test-Path -LiteralPath $Executable
    BridgeRuntimeExists = Test-Path -LiteralPath (Join-Path $BridgeRoot 'runtime.py')
    BridgeCommandExists = Test-Path -LiteralPath (Join-Path $BridgeRoot 'process_pending.py')
    BridgeEventsExist = Test-Path -LiteralPath $EventsRoot
    BridgeManifestValid = $false
    BridgeManifestFingerprint = $null
    BridgeActualFingerprint = $null
    BridgeMatchesHostManifest = $false
    BridgeFileMismatches = @()
    BridgeManifestError = $null
    BridgeCommandImportFilesExist = Test-Path -LiteralPath (Join-Path $BridgeRoot '__init__.py') -PathType Leaf
    BridgeEventImportFilesExist = $false
    CascadeurInstalled = Test-Path -LiteralPath $CascadeurExecutable
    CascadeurVersion = $null
    CascadeurVersionRequired = $PinnedCascadeurVersion
    CascadeurVersionExact = $false
    CascadeurVersionSkipped = [bool]$SkipCascadeurVersion
    SignatureStatus = $null
    CodexAvailable = [bool](Get-Command codex -ErrorAction SilentlyContinue)
    CodexRegistered = $false
    CodexRegisteredPath = $null
    CascadeurCommandRegistered = $false
    CascadeurEventRegistered = $false
    CascadeurPythonPathRegistered = $false
    CascadeurPythonPaths = @()
    CascadeurSettingsError = $null
    McpSmoke = $false
}

$eventFiles = @('__init__.py', 'scene_opened\__init__.py', 'scene_opened\drain.py',
    'scene_activated\__init__.py', 'scene_activated\drain.py')
$checks.BridgeEventImportFilesExist = @($eventFiles | Where-Object {
    -not (Test-Path -LiteralPath (Join-Path $EventsRoot $_) -PathType Leaf)
}).Count -eq 0

try {
    $manifest = Get-Content -LiteralPath $BridgeManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $expected = [Collections.Generic.Dictionary[string,string]]::new([StringComparer]::Ordinal)
    if ($manifest.schema_version -ne 1 -or $manifest.files -isnot [pscustomobject] -or
        [string]$manifest.fingerprint -cnotmatch '^[a-f0-9]{64}$') { throw 'Invalid bridge manifest schema.' }
    foreach ($entry in $manifest.files.PSObject.Properties) {
        $name = [string]$entry.Name
        if ([IO.Path]::IsPathRooted($name) -or $name.Contains('\') -or
            -not $name.EndsWith('.py', [StringComparison]::OrdinalIgnoreCase) -or
            @($name.Split('/') | Where-Object { $_ -in @('', '.', '..') }).Count -or
            [string]$entry.Value -cnotmatch '^[a-f0-9]{64}$') { throw "Invalid bridge manifest file: $name" }
        $expected.Add($name, [string]$entry.Value)
    }
    if (-not $expected.ContainsKey('runtime.py') -or -not $expected.ContainsKey('guarded_runtime.py')) {
        throw 'Bridge manifest is incomplete.'
    }
    $checks.BridgeManifestFingerprint = [string]$manifest.fingerprint
    if ((Get-BridgeFilesFingerprint $expected) -cne $checks.BridgeManifestFingerprint) {
        throw 'Bridge manifest fingerprint does not match its exact file map.'
    }
    $checks.BridgeManifestValid = $true
    $actual = [Collections.Generic.Dictionary[string,string]]::new([StringComparer]::Ordinal)
    $directories = [Collections.Generic.Stack[string]]::new()
    $directories.Push($BridgeRoot)
    while ($directories.Count) {
        $directory = $directories.Pop()
        if ((Get-Item -LiteralPath $directory -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Bridge directory is a reparse point: $directory"
        }
        foreach ($entry in Get-ChildItem -LiteralPath $directory -Force) {
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Bridge entry is a reparse point: $($entry.FullName)" }
            if ($entry.PSIsContainer) { $directories.Push($entry.FullName); continue }
            if ($entry.Extension -ine '.py') { continue }
            $name = $entry.FullName.Substring($BridgeRoot.Length).TrimStart('\').Replace('\', '/')
            $actual.Add($name, (Get-FileHash -LiteralPath $entry.FullName -Algorithm SHA256).Hash.ToLowerInvariant())
        }
    }
    $mismatches = [Collections.Generic.List[object]]::new()
    foreach ($name in $expected.Keys) {
        if (-not $actual.ContainsKey($name)) {
            $mismatches.Add([pscustomobject]@{ Path = $name; Status = 'missing'; ExpectedSha256 = $expected[$name]; ActualSha256 = $null })
        } elseif ($actual[$name] -cne $expected[$name]) {
            $mismatches.Add([pscustomobject]@{ Path = $name; Status = 'changed'; ExpectedSha256 = $expected[$name]; ActualSha256 = $actual[$name] })
        }
    }
    foreach ($name in $actual.Keys) {
        if (-not $expected.ContainsKey($name)) {
            $mismatches.Add([pscustomobject]@{ Path = $name; Status = 'unexpected'; ExpectedSha256 = $null; ActualSha256 = $actual[$name] })
        }
    }
    $checks.BridgeFileMismatches = @($mismatches.ToArray())
    $checks.BridgeActualFingerprint = Get-BridgeFilesFingerprint $actual
    $checks.BridgeMatchesHostManifest = $mismatches.Count -eq 0 -and
        $checks.BridgeActualFingerprint -ceq $checks.BridgeManifestFingerprint
} catch { $checks.BridgeManifestError = $_.Exception.Message }

if ($checks.CascadeurInstalled) {
    $checks.CascadeurVersion = (Get-Item -LiteralPath $CascadeurExecutable).VersionInfo.ProductVersion
    $checks.CascadeurVersionExact = [string]$checks.CascadeurVersion -eq $PinnedCascadeurVersion
}
if ($checks.ExecutableExists) {
    $checks.SignatureStatus = [string](Get-AuthenticodeSignature -LiteralPath $Executable).Status
}
$settingsPath = Join-Path $InstallLocalAppData 'Nekki Limited\Cascadeur\settings.json'
if (Test-Path -LiteralPath $settingsPath) {
    try {
        $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
        $checks.CascadeurCommandRegistered = @($settings.Python.Commands) -ccontains 'cascadeur_complete'
        $checks.CascadeurEventRegistered = @($settings.Python.Events) -ccontains 'cascadeur_complete_events'
        $checks.CascadeurPythonPaths = @($settings.Python.Path)
        $checks.CascadeurPythonPathRegistered = @($settings.Python.Path | Where-Object {
            $_ -is [string] -and [IO.Path]::IsPathRooted($_) -and
            [IO.Path]::GetFullPath($_).TrimEnd('\') -ieq $UserScriptsRoot
        }).Count -gt 0
    } catch { $checks.CascadeurSettingsError = $_.Exception.Message }
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
    'BridgeEventsExist', 'BridgeCommandImportFilesExist', 'BridgeEventImportFilesExist',
    'BridgeManifestValid', 'BridgeMatchesHostManifest',
    'CascadeurCommandRegistered', 'CascadeurEventRegistered', 'CascadeurPythonPathRegistered'
)
if (-not $SkipCascadeurVersion) { $required += @('CascadeurInstalled', 'CascadeurVersionExact') }
if ($checks.CodexAvailable) { $required += 'CodexRegistered' }
if ($RequireSignature) {
    if ($checks.SignatureStatus -ne 'Valid') { $required += 'SignatureValid' }
    $checks.SignatureValid = $checks.SignatureStatus -eq 'Valid'
}

if (-not ($required | Where-Object { -not $checks[$_] })) {
    $SmokeExecutable = if ($checks.CodexAvailable) { $checks.CodexRegisteredPath } else { $Executable }
    # Verify stdio using disposable state, including while Setup owns the real
    # runtime maintenance gate. No auth/state-root bypass enters the server.
    $previousSmokeRoot = $env:CASCADEUR_MCP_ROOT
    $smokeParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    $smokeName = 'cascadeur-mcp-verify-' + [guid]::NewGuid().ToString('N')
    $smokeRoot = [IO.Path]::GetFullPath((Join-Path $smokeParent $smokeName))
    try {
        $env:CASCADEUR_MCP_ROOT = $smokeRoot
        $smokeOutput = & $Executable --smoke --server $SmokeExecutable --timeout 30 2>&1
        $checks.McpSmoke = $LASTEXITCODE -eq 0
        $checks.McpSmokeResult = ($smokeOutput -join "`n")
    } finally {
        if ($null -eq $previousSmokeRoot) { Remove-Item Env:CASCADEUR_MCP_ROOT -ErrorAction SilentlyContinue }
        else { $env:CASCADEUR_MCP_ROOT = $previousSmokeRoot }
        # This exact GUID child is owned by this invocation, never RuntimeRoot.
        if ((Split-Path -Parent $smokeRoot) -ine $smokeParent -or (Split-Path -Leaf $smokeRoot) -cne $smokeName) {
            throw 'Disposable verification state escaped its temporary parent.'
        }
        if (Test-Path -LiteralPath $smokeRoot) {
            if ((Get-Item -LiteralPath $smokeRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Disposable verification state is a reparse point.'
            }
            Remove-Item -LiteralPath $smokeRoot -Recurse -Force
        }
        $smokeGate = Join-Path (Split-Path -Parent $smokeRoot) ('.' + (Split-Path -Leaf $smokeRoot) + '.maintenance.lock')
        if (Test-Path -LiteralPath $smokeGate) { Remove-Item -LiteralPath $smokeGate -Force }
    }
}
$required += 'McpSmoke'

$checks | ConvertTo-Json -Depth 10
if ($required | Where-Object { -not $checks[$_] }) { exit 1 }
