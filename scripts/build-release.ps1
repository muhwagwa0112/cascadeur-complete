[CmdletBinding()]
param(
    [switch] $SkipInstaller,
    [switch] $InstallerOnly,
    [switch] $RequireSignature
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$ArtifactsRoot = [IO.Path]::GetFullPath((Join-Path $ProjectRoot 'artifacts'))
if (-not $ArtifactsRoot.StartsWith($ProjectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use artifacts path outside the workspace: $ArtifactsRoot"
}
$StageRoot = Join-Path $ArtifactsRoot 'stage'
$InstallerRoot = Join-Path $ArtifactsRoot 'installer'
$VersionMatch = Select-String -LiteralPath (Join-Path $ProjectRoot 'pyproject.toml') -Pattern '^version\s*=\s*"([^"]+)"'
if (-not $VersionMatch) { throw 'Unable to read project version' }
$Version = $VersionMatch.Matches[0].Groups[1].Value

function Assert-ValidSignature([string] $Path) {
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid') { throw "Authenticode signature is not valid for ${Path}: $($signature.Status)" }
}

if (-not $InstallerOnly) {
    if (Test-Path -LiteralPath $ArtifactsRoot) { Remove-Item -LiteralPath $ArtifactsRoot -Recurse -Force }
    New-Item -ItemType Directory -Path $ArtifactsRoot, $StageRoot, $InstallerRoot -Force | Out-Null
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv is required to build from source' }

    $BuildVenv = Join-Path $ArtifactsRoot 'build-venv'
    & uv venv --python 3.12 $BuildVenv
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create isolated Python 3.12 build environment' }
    $Python = Join-Path $BuildVenv 'Scripts\python.exe'
    & uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file (Join-Path $ArtifactsRoot 'runtime-requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'uv.lock export failed' }
    & uv pip install --python $Python --requirement (Join-Path $ArtifactsRoot 'runtime-requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Locked runtime dependency installation failed' }
    & uv pip install --python $Python --requirement (Join-Path $ProjectRoot 'packaging\requirements-build.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Pinned build dependency installation failed' }
    & uv pip install --python $Python --no-deps $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Project installation failed' }

    $DistRoot = Join-Path $ArtifactsRoot 'pyinstaller-dist'
    $WorkRoot = Join-Path $ArtifactsRoot 'pyinstaller-work'
    & $Python -m PyInstaller --noconfirm --clean --onedir --name cascadeur-complete `
        --distpath $DistRoot --workpath $WorkRoot --specpath $ArtifactsRoot `
        --paths (Join-Path $ProjectRoot 'src') --paths (Join-Path $ProjectRoot 'packaging') `
        --hidden-import win32api `
        --collect-data cascadeur_complete `
        --version-file (Join-Path $ProjectRoot 'packaging\windows_version_info.txt') `
        (Join-Path $ProjectRoot 'packaging\server_entry.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }

    $RawServer = Join-Path $DistRoot 'cascadeur-complete\cascadeur-complete.exe'
    $previousSmokeRoot = $env:CASCADEUR_MCP_ROOT
    try {
        $env:CASCADEUR_MCP_ROOT = Join-Path $ArtifactsRoot 'raw-dist-smoke-state'
        & $RawServer --smoke --server $RawServer --timeout 30
        if ($LASTEXITCODE -ne 0) { throw 'Raw frozen MCP stdio smoke failed' }
    } finally {
        if ($null -eq $previousSmokeRoot) { Remove-Item Env:CASCADEUR_MCP_ROOT -ErrorAction SilentlyContinue }
        else { $env:CASCADEUR_MCP_ROOT = $previousSmokeRoot }
    }

    $AppStage = Join-Path $StageRoot 'app'
    New-Item -ItemType Directory -Path $AppStage -Force | Out-Null
    Copy-Item -Path (Join-Path $DistRoot 'cascadeur-complete\*') -Destination $AppStage -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'policy.default.json') -Destination (Join-Path $AppStage 'policy.default.json')
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'policy.default.json') -Destination (Join-Path $AppStage 'policy.json')
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'LICENSE') -Destination $AppStage
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'THIRD_PARTY_NOTICES.md') -Destination $AppStage
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'README.md') -Destination $AppStage
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'inventory') -Destination $AppStage -Recurse

    $SupportStage = Join-Path $AppStage 'support'
    New-Item -ItemType Directory -Path $SupportStage -Force | Out-Null
    foreach ($supportFile in @('install-hooks.ps1', 'uninstall-hooks.ps1', 'post-uninstall-restore.ps1')) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot "packaging\$supportFile") -Destination $SupportStage
    }
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'scripts\verify-install.ps1') -Destination $SupportStage

    $BridgeStage = Join-Path $StageRoot 'bridge'
    New-Item -ItemType Directory -Path $BridgeStage -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'cascadeur_side\cascadeur_complete') -Destination $BridgeStage -Recurse
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'cascadeur_side\cascadeur_complete_events') -Destination $BridgeStage -Recurse

    $Server = Join-Path $AppStage 'cascadeur-complete.exe'
    $previousSmokeRoot = $env:CASCADEUR_MCP_ROOT
    try {
        $env:CASCADEUR_MCP_ROOT = Join-Path $ArtifactsRoot 'smoke-state'
        & $Server --smoke --server $Server --timeout 30
        if ($LASTEXITCODE -ne 0) { throw 'Staged frozen MCP stdio smoke failed' }
    } finally {
        if ($null -eq $previousSmokeRoot) { Remove-Item Env:CASCADEUR_MCP_ROOT -ErrorAction SilentlyContinue }
        else { $env:CASCADEUR_MCP_ROOT = $previousSmokeRoot }
    }
    $FrozenVersion = (Get-Item -LiteralPath $Server).VersionInfo.ProductVersion
    if ([string]$FrozenVersion -ne $Version) {
        throw "Frozen ProductVersion $FrozenVersion does not match pyproject version $Version"
    }

    $Sbom = Join-Path $ArtifactsRoot 'cascadeur-mcp.cdx.json'
    $previousUtf8 = $env:PYTHONUTF8
    $env:PYTHONUTF8 = '1'
    & $Python -m cyclonedx_py requirements (Join-Path $ArtifactsRoot 'runtime-requirements.txt') --output-format JSON --output-file $Sbom
    $env:PYTHONUTF8 = $previousUtf8
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Sbom)) { throw 'CycloneDX SBOM generation failed' }
    & $Python (Join-Path $ProjectRoot 'packaging\finalize_sbom.py') --sbom $Sbom --app $AppStage --version $Version
    if ($LASTEXITCODE -ne 0) { throw 'Final artifact SBOM binding failed' }
}

if ($RequireSignature) {
    Get-ChildItem -LiteralPath (Join-Path $StageRoot 'app') -Filter '*.exe' -Recurse | ForEach-Object {
        Assert-ValidSignature $_.FullName
    }
}

if (-not $SkipInstaller) {
    $iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if (-not $iscc) {
        $known = @(
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
            (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
        if ($known) { $iscc = Get-Item -LiteralPath $known }
    }
    if (-not $iscc) { throw 'Inno Setup 6 compiler (ISCC.exe) is required; use -SkipInstaller for app-only builds' }
    & $iscc.Source "/DMyAppVersion=$Version" "/DStageRoot=$StageRoot" (Join-Path $ProjectRoot 'installer\cascadeur-mcp.iss')
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed' }
}

if ($RequireSignature -and (Test-Path -LiteralPath $InstallerRoot)) {
    Get-ChildItem -LiteralPath $InstallerRoot -Filter '*.exe' | ForEach-Object { Assert-ValidSignature $_.FullName }
}

$releaseFiles = @()
if (Test-Path -LiteralPath $InstallerRoot) { $releaseFiles += Get-ChildItem -LiteralPath $InstallerRoot -File }
$sbomPath = Join-Path $ArtifactsRoot 'cascadeur-mcp.cdx.json'
if (Test-Path -LiteralPath $sbomPath) { $releaseFiles += Get-Item -LiteralPath $sbomPath }
$manifest = foreach ($file in $releaseFiles) {
    [ordered]@{ file = $file.Name; bytes = $file.Length; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant() }
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $ArtifactsRoot 'SHA256SUMS.json') -Encoding utf8
[pscustomobject]@{ Version = $Version; Artifacts = $ArtifactsRoot; Files = $manifest; Signed = [bool]$RequireSignature } | ConvertTo-Json -Depth 6
