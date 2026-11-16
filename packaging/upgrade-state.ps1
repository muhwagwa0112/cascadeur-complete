# Shared by source and frozen installers. Never imports the incoming runtime.
# Child Windows PowerShell may inherit PowerShell 7's PSModulePath. Load this
# interpreter's shipped Utility manifest explicitly (including Get-FileHash),
# without changing the parent environment, execution policy or installed state.
Import-Module -Name (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -ErrorAction Stop

function Get-CascadeurLocalAppData {
    if ($env:USERPROFILE) {
        $candidate = Join-Path $env:USERPROFILE 'AppData\Local'
        if (Test-Path -LiteralPath $candidate -PathType Container) { return [IO.Path]::GetFullPath($candidate) }
    }
    if (-not $env:LOCALAPPDATA) { throw 'Local AppData is unavailable.' }
    return [IO.Path]::GetFullPath($env:LOCALAPPDATA)
}

function Get-CascadeurMaintenancePath([string] $RuntimeRoot) {
    $runtime = [IO.Path]::GetFullPath($RuntimeRoot).TrimEnd('\')
    $parent = Split-Path -Parent $runtime
    $leaf = Split-Path -Leaf $runtime
    if (-not $parent -or -not $leaf) { throw 'A runtime directory beneath a parent is required for maintenance.' }
    # Keep the gate outside the renamed/replaced runtime. Its bytes/existence
    # are not state or authorization; only live Windows sharing handles matter.
    return Join-Path $parent ('.' + $leaf + '.maintenance.lock')
}

function Enter-CascadeurMaintenanceLease([string] $RuntimeRoot) {
    $gate = Get-CascadeurMaintenancePath $RuntimeRoot
    $ancestor = $gate
    while ($ancestor) {
        $entry = Get-Item -LiteralPath $ancestor -Force -ErrorAction SilentlyContinue
        if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Maintenance gate has a reparse ancestor.'
        }
        $parent = Split-Path -Parent $ancestor
        if ($parent -eq $ancestor) { break }
        $ancestor = $parent
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $gate) -Force | Out-Null
    try {
        # Non-inheritable process-owned exclusive handle. Runtime readers use
        # GENERIC_READ/FILE_SHARE_READ, so either existing readers or another
        # installer make this open fail immediately, without an existence test.
        return [IO.File]::Open($gate, [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch {
        throw "Unable to acquire maintenance lease at ${gate}. Close the installed runtime and any other installer. $($_.Exception.Message)"
    }
}

function Assert-CascadeurUpgradeIdle([string] $RuntimeRoot) {
    $prefix = [IO.Path]::GetFullPath($RuntimeRoot).TrimEnd('\') + '\'
    $busy = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.ProcessId -ne $PID -and (
            $_.Name -ieq 'cascadeur.exe' -or
            ($_.ExecutablePath -and ([string]$_.ExecutablePath).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) -or
            ($_.CommandLine -and ([string]$_.CommandLine).IndexOf($prefix, [StringComparison]::OrdinalIgnoreCase) -ge 0)
        )
    })
    if ($busy.Count) { throw ('Close Cascadeur and the installed MCP before upgrading (PIDs: ' + (($busy | ForEach-Object ProcessId) -join ', ') + ').') }
}

function Get-CascadeurRuntimeCodeNames {
    # These are the source installer and build-release.ps1 payload entries.
    # Persistent state, user-added root files and Inno's own uninstall metadata
    # are not runtime code owned by this transaction.
    return @('.venv', 'src', 'inventory', 'support', '_internal',
        'pyproject.toml', 'uv.lock', 'README.md', 'LICENSE',
        'THIRD_PARTY_NOTICES.md', 'policy.default.json',
        'bridge-package.json', 'cascadeur-complete.exe')
}

function Get-CascadeurInstallIdentity([string] $Path) {
    # Query directory/file IDs, not timestamps or a copied marker. The runtime
    # root must retain this identity throughout activation and rollback.
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $ancestor = $full
    while ($ancestor) {
        $item = Get-Item -LiteralPath $ancestor -Force -ErrorAction Stop
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Redirected install path: $ancestor" }
        $parent = Split-Path -Parent $ancestor
        if ($parent -eq $ancestor) { break }
        $ancestor = $parent
    }
    if (-not ('CascadeurInstallIdentityV1' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class CascadeurInstallIdentityV1 {
  [StructLayout(LayoutKind.Sequential)] struct FileId {
    public ulong Volume;
    [MarshalAs(UnmanagedType.ByValArray, SizeConst=16)] public byte[] Id;
  }
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  static extern SafeFileHandle CreateFile(string path, uint access, uint share,
    IntPtr security, uint creation, uint flags, IntPtr template);
  [DllImport("kernel32.dll", SetLastError=true)]
  static extern bool GetFileInformationByHandleEx(SafeFileHandle handle, int kind,
    out FileId identity, uint size);
  public static string Read(string path) {
    using (var handle = CreateFile(path, 0, 7, IntPtr.Zero, 3, 0x02200000, IntPtr.Zero)) {
      if (handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
      FileId value;
      if (!GetFileInformationByHandleEx(handle, 18, out value, (uint)Marshal.SizeOf(typeof(FileId))))
        throw new Win32Exception(Marshal.GetLastWin32Error());
      return value.Volume.ToString("x16") + ":" + BitConverter.ToString(value.Id).Replace("-", "").ToLowerInvariant();
    }
  }
}

'@
    }
    return [pscustomobject]@{ path = $full; file_identity = [CascadeurInstallIdentityV1]::Read($full) }
}

function Get-CascadeurDirectoryAcl([string] $Path) {
    # Direct Windows ACL APIs avoid child powershell.exe inheriting an
    # incompatible PSModulePath and failing Security-module autoload.
    if ($PSVersionTable.PSVersion.Major -lt 6) { return [IO.Directory]::GetAccessControl($Path) }
    return [IO.FileSystemAclExtensions]::GetAccessControl([IO.DirectoryInfo]::new($Path))
}

function Set-CascadeurDirectoryAcl([string] $Path, [object] $Acl) {
    if ($PSVersionTable.PSVersion.Major -lt 6) { [IO.Directory]::SetAccessControl($Path, $Acl) }
    else { [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($Path), $Acl) }
}

function Assert-CascadeurRuntimeIdentity([object] $RuntimeState) {
    if ($RuntimeState.existed -and -not @($RuntimeState.retained_identities).Count) {
        throw 'The transaction has no original runtime physical identity; automatic state reconstruction is unsupported.'
    }
    foreach ($saved in @($RuntimeState.retained_identities)) {
        if ($null -eq $saved) { continue }
        $actual = Get-CascadeurInstallIdentity ([string]$saved.path)
        if ($actual.file_identity -cne [string]$saved.file_identity) {
            throw "Retained install identity changed: $($saved.path). Refusing to reconstruct authenticated state."
        }
    }
    if ($RuntimeState.policy_existed -and $RuntimeState.policy_sha256) {
        $policy = Join-Path ([string]$RuntimeState.path) 'policy.json'
        if ((Get-FileHash -LiteralPath $policy -Algorithm SHA256).Hash -cne [string]$RuntimeState.policy_sha256) {
            throw 'Retained policy bytes changed during installation; refusing to overwrite them.'
        }
    }
}

function Get-CascadeurRuntimeCodeEntries([string] $RuntimeRoot) {
    if (-not (Test-Path -LiteralPath $RuntimeRoot)) { return }
    $root = Get-Item -LiteralPath $RuntimeRoot -Force
    if (-not $root.PSIsContainer -or ($root.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'The runtime must be a non-redirected directory.'
    }
    foreach ($name in (Get-CascadeurRuntimeCodeNames)) {
        $path = Join-Path $RuntimeRoot $name
        if (-not (Test-Path -LiteralPath $path)) { continue }
        $entry = Get-Item -LiteralPath $path -Force
        $tree = @($entry)
        if ($entry.PSIsContainer) { $tree += @(Get-ChildItem -LiteralPath $path -Recurse -Force) }
        if (@($tree | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
            throw "Runtime code contains a redirected entry: $path"
        }
        $entry
    }
}

function Backup-CascadeurRuntimeCode([string] $RuntimeRoot, [string] $BackupRoot) {
    $runtime = [IO.Path]::GetFullPath($RuntimeRoot)
    $codeBackup = Join-Path $BackupRoot 'runtime-code'
    # Refuse to reuse another transaction's preimage, including timestamp collisions.
    New-Item -ItemType Directory -Path $codeBackup -ErrorAction Stop | Out-Null
    $entries = @(Get-CascadeurRuntimeCodeEntries $runtime)
    $retained = @()
    foreach ($path in @($runtime, (Join-Path $runtime 'state'), (Join-Path $runtime 'snapshots'), (Join-Path $runtime 'logs'))) {
        if (Test-Path -LiteralPath $path) { $retained += Get-CascadeurInstallIdentity $path }
    }
    $state = Join-Path $runtime 'state'
    $stateExisted = Test-Path -LiteralPath $state
    $stateSddl = $null
    if ($stateExisted) {
        $stateEntry = Get-Item -LiteralPath $state -Force
        if (-not $stateEntry.PSIsContainer -or ($stateEntry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'The retained state directory must not be redirected.'
        }
        $stateSddl = (Get-CascadeurDirectoryAcl $state).GetSecurityDescriptorSddlForm(
            [Security.AccessControl.AccessControlSections]::Access)
    }
    $ownership = Join-Path $state 'install-ownership.json'
    $ownershipExisted = Test-Path -LiteralPath $ownership
    $ownershipHash = $null
    if ($ownershipExisted) {
        $ownerEntry = Get-Item -LiteralPath $ownership -Force
        if ($ownerEntry.PSIsContainer -or ($ownerEntry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'The installer ownership record must be a regular file.'
        }
        Copy-Item -LiteralPath $ownership -Destination (Join-Path $BackupRoot 'runtime-install-ownership.json')
        $ownershipHash = (Get-FileHash -LiteralPath $ownership -Algorithm SHA256).Hash
        if ((Get-FileHash -LiteralPath (Join-Path $BackupRoot 'runtime-install-ownership.json') -Algorithm SHA256).Hash -cne $ownershipHash) {
            throw 'Installer ownership preimage changed bytes.'
        }
    }
    foreach ($entry in $entries) {
        Copy-Item -LiteralPath $entry.FullName -Destination $codeBackup -Recurse -Force
    }
    $codeManifest = @(Get-CascadeurRuntimeCodeManifest $runtime)
    Assert-CascadeurRuntimeCodeManifest $codeBackup $codeManifest
    return [pscustomobject]@{
        path = $runtime
        existed = [bool](Test-Path -LiteralPath $runtime)
        code_entries = @($entries | ForEach-Object Name)
        state_existed = [bool]$stateExisted
        state_acl_sddl = $stateSddl
        ownership_existed = [bool]$ownershipExisted
        ownership_sha256 = $ownershipHash
        policy_existed = [bool](Test-Path -LiteralPath (Join-Path $runtime 'policy.json'))
        policy_sha256 = if (Test-Path -LiteralPath (Join-Path $runtime 'policy.json')) {
            (Get-FileHash -LiteralPath (Join-Path $runtime 'policy.json') -Algorithm SHA256).Hash
        } else { $null }
        retained_identities = @($retained)
        code_manifest = @($codeManifest)
    }
}

function Get-CascadeurRuntimeCodeManifest([string] $RuntimeRoot) {
    $prefix = [IO.Path]::GetFullPath($RuntimeRoot).TrimEnd('\') + '\'
    $files = @()
    foreach ($entry in @(Get-CascadeurRuntimeCodeEntries $RuntimeRoot)) {
        if ($entry.PSIsContainer) { $files += @(Get-ChildItem -LiteralPath $entry.FullName -Recurse -Force -File) }
        else { $files += $entry }
    }
    foreach ($file in @($files | Sort-Object FullName)) {
        [pscustomobject]@{ path = $file.FullName.Substring($prefix.Length); size = $file.Length;
            sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash }
    }
}

function Assert-CascadeurRuntimeCodeManifest([string] $RuntimeRoot, [object[]] $Expected) {
    $actual = @(Get-CascadeurRuntimeCodeManifest $RuntimeRoot)
    $expectedRows = @($Expected | ForEach-Object { "$($_.path)|$($_.size)|$($_.sha256)" })
    $actualRows = @($actual | ForEach-Object { "$($_.path)|$($_.size)|$($_.sha256)" })
    if (($expectedRows -join "`n") -cne ($actualRows -join "`n")) {
        throw "Runtime code preimage bytes or file set differ: $RuntimeRoot"
    }
}

function Clear-CascadeurRuntimeCode([string] $RuntimeRoot) {
    # Materialize the checked set before deleting the first code child.
    $entries = @(Get-CascadeurRuntimeCodeEntries $RuntimeRoot)
    foreach ($entry in $entries) {
        Remove-Item -LiteralPath $entry.FullName -Recurse -Force
    }
}

function Restore-CascadeurRuntimeCode([object] $RuntimeState, [string] $BackupRoot) {
    $runtime = [IO.Path]::GetFullPath([string]$RuntimeState.path)
    Assert-CascadeurRuntimeIdentity $RuntimeState
    if ($RuntimeState.existed -and -not (Test-Path -LiteralPath $runtime -PathType Container)) {
        throw 'The original runtime root is missing; do not recreate its authenticated identity.'
    }
    $codeBackup = Join-Path $BackupRoot 'runtime-code'
    if ($null -eq $RuntimeState.PSObject.Properties['code_manifest']) {
        throw 'The transaction has no verified code preimage; refusing an unverifiable rollback.'
    }
    Assert-CascadeurRuntimeCodeManifest $codeBackup @($RuntimeState.code_manifest)
    $names = @(Get-CascadeurRuntimeCodeNames)
    foreach ($name in @($RuntimeState.code_entries)) {
        if ($name -notin $names -or -not (Test-Path -LiteralPath (Join-Path $codeBackup $name))) {
            throw "Runtime code preimage is missing or invalid: $name"
        }
    }
    $ownershipBackup = Join-Path $BackupRoot 'runtime-install-ownership.json'
    if ($RuntimeState.ownership_existed -and -not (Test-Path -LiteralPath $ownershipBackup -PathType Leaf)) {
        throw 'Installer ownership preimage is missing.'
    }
    if ($RuntimeState.ownership_existed -and
        (Get-FileHash -LiteralPath $ownershipBackup -Algorithm SHA256).Hash -cne [string]$RuntimeState.ownership_sha256) {
        throw 'Installer ownership preimage bytes differ.'
    }
    $state = Join-Path $runtime 'state'
    if ($RuntimeState.state_existed -and -not (Test-Path -LiteralPath $state -PathType Container)) {
        throw 'The original state directory is missing; retained state cannot be reconstructed from code backup.'
    }
    # Only remove an initial policy if it still equals the default this install
    # supplied. A pre-existing or subsequently edited policy is always retained.
    $policy = Join-Path $runtime 'policy.json'
    $defaultPolicy = Join-Path $runtime 'policy.default.json'
    $removeInitialPolicy = -not $RuntimeState.policy_existed -and
        (Test-Path -LiteralPath $policy -PathType Leaf) -and
        (Test-Path -LiteralPath $defaultPolicy -PathType Leaf) -and
        ((Get-FileHash -LiteralPath $policy -Algorithm SHA256).Hash -eq
         (Get-FileHash -LiteralPath $defaultPolicy -Algorithm SHA256).Hash)
    Clear-CascadeurRuntimeCode $runtime
    New-Item -ItemType Directory -Path $runtime -Force | Out-Null
    foreach ($name in @($RuntimeState.code_entries)) {
        Copy-Item -LiteralPath (Join-Path $codeBackup $name) -Destination $runtime -Recurse -Force
    }
    Assert-CascadeurRuntimeCodeManifest $runtime @($RuntimeState.code_manifest)
    $ownership = Join-Path $state 'install-ownership.json'
    if ($RuntimeState.ownership_existed) {
        Copy-Item -LiteralPath $ownershipBackup -Destination $ownership -Force
    } elseif (Test-Path -LiteralPath $ownership) {
        Remove-Item -LiteralPath $ownership -Force
    }
    if ($RuntimeState.state_existed) {
        $acl = Get-CascadeurDirectoryAcl $state
        $acl.SetSecurityDescriptorSddlForm([string]$RuntimeState.state_acl_sddl,
            [Security.AccessControl.AccessControlSections]::Access)
        Set-CascadeurDirectoryAcl $state $acl
    } elseif ((Test-Path -LiteralPath $state -PathType Container) -and
              @(Get-ChildItem -LiteralPath $state -Force).Count -eq 0) {
        Remove-Item -LiteralPath $state
    }
    if ($removeInitialPolicy) { Remove-Item -LiteralPath $policy -Force }
    # A fresh install may leave new evidence or user data behind. Remove only
    # an empty root we created; never delete an existing authenticated root.
    if (-not $RuntimeState.existed -and @(Get-ChildItem -LiteralPath $runtime -Force).Count -eq 0) {
        Remove-Item -LiteralPath $runtime
    }
    Assert-CascadeurRuntimeIdentity $RuntimeState
}

function Copy-CascadeurPersistentState([string] $PreviousRuntime, [string] $NextRuntime) {
    $previous = [IO.Path]::GetFullPath($PreviousRuntime).TrimEnd('\')
    $next = [IO.Path]::GetFullPath($NextRuntime).TrimEnd('\')
    if ($previous -ieq $next -or $previous.StartsWith($next + '\', [StringComparison]::OrdinalIgnoreCase) -or
        $next.StartsWith($previous + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'State migration needs separate, non-nested runtime directories.'
    }
    if (-not (Test-Path -LiteralPath $previous)) { return }
    foreach ($root in @($previous, $next)) {
        $ancestor = $root
        while ($ancestor) {
            if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'State root has a reparse ancestor.' }
            $parent = Split-Path -Parent $ancestor
            if ($parent -eq $ancestor) { break }
            $ancestor = $parent
        }
    }
    # Preserve the complete authenticated history, including unknown outcomes,
    # consumed permits, keys, snapshots and references. Do not interpret records.
    foreach ($name in @('state', 'snapshots', 'logs', 'policy.json')) {
        $source = Join-Path $previous $name
        if (-not (Test-Path -LiteralPath $source)) { continue }
        $entries = @((Get-Item -LiteralPath $source -Force))
        if ($entries[0].PSIsContainer) { $entries += @(Get-ChildItem -LiteralPath $source -Recurse -Force) }
        foreach ($entry in $entries) {
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Persistent state contains a reparse point; migration stopped.' }
            $relative = $entry.FullName.Substring($previous.Length).TrimStart('\')
            $target = [IO.Path]::GetFullPath((Join-Path $next $relative))
            if (-not $target.StartsWith($next + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'State migration escaped the target.' }
            $parent = Split-Path -Parent $target
            while ($parent.Length -ge $next.Length) {
                if ((Test-Path -LiteralPath $parent) -and ((Get-Item -LiteralPath $parent -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Persistent target has a reparse ancestor.' }
                $parent = Split-Path -Parent $parent
            }
            if ($entry.PSIsContainer) { New-Item -ItemType Directory -Path $target -Force | Out-Null; continue }
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            if (Test-Path -LiteralPath $target) {
                if ((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Persistent target is a reparse point.' }
                if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $entry.FullName -Algorithm SHA256).Hash) {
                    throw ('Conflicting persistent state: ' + $relative)
                }
            } else { Copy-Item -LiteralPath $entry.FullName -Destination $target }
            if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $entry.FullName -Algorithm SHA256).Hash) { throw 'Persistent state copy changed bytes.' }
        }
    }
}
