# R6 reference only. No OS/product execution was performed when preparing it.
# Capture is a trusted-supervisor operation, never a caller-accessible signing RPC.
# Verify is the guest-side standard Windows/.NET crypto boundary.
# A separately provisioned host, protected approved-plan/key/script files and an
# exclusive supervisor controller are PRECONDITIONS, not conclusions of this code.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('Capture','Verify')][string]$Mode,
    [Parameter(Mandatory=$true)][string]$EnvelopePath,
    [Parameter(Mandatory=$true)][string]$ExpectedCertificateSha256,
    [string]$CertificatePath,
    [string]$CertificateThumbprint,
    [string]$ApprovedPlanPath,
    [string]$ExpectedPlanSha256,
    [string]$BindingPath,
    [string]$ExpectedBindingSha256,
    [string]$Challenge
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false, $true)

function Hash-Bytes([byte[]]$Bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function Require-Hash([string]$Value) {
    if ($Value -cnotmatch '^[a-f0-9]{64}$') { throw 'INVALID_SHA256' }
}
function Required-Property($Object, [string]$Name) {
    if ($null -eq $Object.PSObject.Properties[$Name]) { throw "OS_PROPERTY_UNAVAILABLE:$Name" }
    return $Object.$Name
}
function Read-PinnedBytes([string]$Path, [string]$Expected) {
    Require-Hash $Expected
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ((Hash-Bytes $bytes) -cne $Expected) { throw 'PINNED_BYTES_DIFFER' }
    return ,$bytes
}
function Publish-New([string]$Path, [byte[]]$Bytes) {
    # Parent directory belongs to the supervisor and must already exist.
    # CreateNew prevents overwriting evidence. Flush(true) precedes publication.
    $temporary = $Path + '.' + [Guid]::NewGuid().ToString('N') + '.pending'
    $stream = [System.IO.File]::Open($temporary, [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try { $stream.Write($Bytes,0,$Bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
    # A crash can leave .pending; it never becomes an admission grant.
    [System.IO.File]::Move($temporary, $Path)
}

Require-Hash $ExpectedCertificateSha256
if ($Mode -eq 'Verify') {
    $certificateBytes = Read-PinnedBytes $CertificatePath $ExpectedCertificateSha256
    $certificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 -ArgumentList @(,$certificateBytes)
    $envelope = $utf8.GetString([System.IO.File]::ReadAllBytes($EnvelopePath)) | ConvertFrom-Json
    if ($envelope.schema_version -ne 1 -or $envelope.algorithm -cne 'RS256-PKCS1'
        -or $envelope.certificate_sha256 -cne $ExpectedCertificateSha256) { throw 'SIGNATURE_ENVELOPE_DIFFERS' }
    $data = [Convert]::FromBase64String($envelope.payload_b64)
    $signature = [Convert]::FromBase64String($envelope.signature_b64)
    $rsa = [System.Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPublicKey($certificate)
    if ($null -eq $rsa) { throw 'RSA_PUBLIC_KEY_REQUIRED' }
    try {
        $valid = $rsa.VerifyData($data, $signature,
            [System.Security.Cryptography.HashAlgorithmName]::SHA256,
            [System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
        if (-not $valid) { throw 'STANDARD_RSA_VERIFICATION_FAILED' }
        # Python compares these EXACT bytes with the input envelope payload.
        # No JSON boolean is accepted as a verification result.
        [Console]::Out.Write([Convert]::ToBase64String($data))
    } finally { $rsa.Dispose(); $certificate.Dispose() }
    exit 0
}

if ($Challenge -cnotmatch '^[a-f0-9]{64}$') { throw 'FRESH_CHALLENGE_REQUIRED' }
$planBytes = Read-PinnedBytes $ApprovedPlanPath $ExpectedPlanSha256
$bindingBytes = Read-PinnedBytes $BindingPath $ExpectedBindingSha256
$plan = $utf8.GetString($planBytes) | ConvertFrom-Json
$binding = $utf8.GetString($bindingBytes) | ConvertFrom-Json
if ($plan.schema_version -ne 1 -or $plan.purpose -cne 'independent_target_plan_v1'
    -or $plan.profile -cne 'dedicated_hyperv_no_external_devices_v1'
    -or $plan.control_transport -cne 'powershell_direct_fixed_files_v1'
    -or $plan.baseline.origin_kind -cne 'immutable_fixture_generator'
    -or $binding.schema_version -ne 1 -or $binding.purpose -cne 'realm_capture_binding_v1'
    -or $binding.approved_plan_sha256 -cne $ExpectedPlanSha256
    -or $binding.challenge -cne $Challenge
    -or $binding.kind -cnotin @('coverage','prepare','dispatch','first_effect','observe_off')) {
    throw 'UNSUPPORTED_PLAN_OR_CAPTURE_BINDING'
}
$nowMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
if ($plan.expires_at_ms -le $nowMs) { throw 'APPROVED_PLAN_EXPIRED' }
$controllerSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if ($controllerSid -cne $plan.controller_sid) { throw 'CONTROLLER_IDENTITY_DIFFERS' }

# All calls below must be present and successful. An absent cmdlet is never []:
Import-Module Hyper-V -ErrorAction Stop
@('Get-VM','Get-VMHost','Get-VMHardDiskDrive','Get-VHD','Get-VMNetworkAdapter',
  'Get-VMAssignableDevice','Get-VMGpuPartitionAdapter','Get-VMFibreChannelHba',
  'Get-VMComPort','Get-VMDvdDrive','Get-VMSnapshot','Get-VMIntegrationService') |
    ForEach-Object { $null = Get-Command $_ -ErrorAction Stop }
$vm = Get-VM -Id ([Guid]$plan.realm.vm_id) -ErrorAction Stop
if ($vm.Generation -ne 2 -or $vm.Id.ToString() -cne $plan.realm.vm_id) { throw 'VM_IDENTITY_DIFFERS' }
$state = $vm.State.ToString()
$requiredState = if ($binding.kind -ceq 'observe_off') { 'Off' } else { 'Running' }
if ($state -cne $requiredState) { throw 'VM_STATE_NOT_ADMISSIBLE' }
$hostInfo = Get-VMHost -ErrorAction Stop
if ((Required-Property $hostInfo 'EnableEnhancedSessionMode') -ne $false) { throw 'ENHANCED_SESSION_ENABLED' }
$hardware = Get-CimInstance -ClassName Win32_ComputerSystemProduct -ErrorAction Stop
$hostUuid = ([Guid]$hardware.UUID).ToString()
if ($hostUuid -cne $plan.realm.host_uuid) { throw 'APPROVED_HOST_DIFFERS' }
$os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
$vmSystem = Get-CimInstance -Namespace 'root/virtualization/v2' -ClassName Msvm_ComputerSystem `
    -Filter ("Name='" + $vm.Id.ToString() + "'") -ErrorAction Stop
if (@($vmSystem).Count -ne 1 -or (Required-Property $vmSystem 'ReplicationMode') -ne 0) { throw 'VM_REPLICATION_OR_IDENTITY_DIFFERS' }

$nics = @(Get-VMNetworkAdapter -VM $vm -ErrorAction Stop)
$dda = @(Get-VMAssignableDevice -VM $vm -ErrorAction Stop)
$gpu = @(Get-VMGpuPartitionAdapter -VM $vm -ErrorAction Stop)
$fibre = @(Get-VMFibreChannelHba -VM $vm -ErrorAction Stop)
$snapshots = @(Get-VMSnapshot -VM $vm -ErrorAction Stop)
$com = @(Get-VMComPort -VM $vm -ErrorAction Stop)
$dvd = @(Get-VMDvdDrive -VM $vm -ErrorAction Stop)
$integration = @(Get-VMIntegrationService -VM $vm -ErrorAction Stop)
if ($nics.Count -or $dda.Count -or $gpu.Count -or $fibre.Count -or $snapshots.Count) { throw 'EXTERNAL_DEVICE_OR_CHECKPOINT_PRESENT' }
foreach ($port in $com) { if (Required-Property $port 'Path') { throw 'COM_PIPE_PRESENT' } }
foreach ($drive in $dvd) { if (Required-Property $drive 'Path') { throw 'DVD_MEDIA_PRESENT' } }
foreach ($service in $integration) {
    if ((Required-Property $service 'Enabled') -ne $false) { throw 'INTEGRATION_SERVICE_ENABLED' }
}

# File identities use the real Windows handle API. This is metadata capture,
# not a claim that same-user ACLs constitute an independent trust boundary.
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class R6FileIdentity {
  [StructLayout(LayoutKind.Sequential)] public struct Info {
    public uint Attributes, CreateLow, CreateHigh, AccessLow, AccessHigh,
      WriteLow, WriteHigh, Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
  }
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  private static extern SafeFileHandle CreateFile(string path, uint access,
      uint share, IntPtr security, uint disposition, uint flags, IntPtr template);
  [DllImport("kernel32.dll", SetLastError=true)]
  private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
  public static Info Read(string path) {
    using (var handle=CreateFile(path,0,7,IntPtr.Zero,3,0,IntPtr.Zero)) {
      if(handle.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
      Info info;
      if(!GetFileInformationByHandle(handle,out info)) throw new Win32Exception(Marshal.GetLastWin32Error());
      return info;
    }
  }
}
'@
function Local-FileIdentity([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full.StartsWith('\\') -or $full.Substring(2).Contains(':')) { throw 'REMOTE_OR_STREAM_PATH_FORBIDDEN' }
    $driveInfo = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($full))
    if ($driveInfo.DriveType -ne [IO.DriveType]::Fixed) { throw 'LOCAL_FIXED_DISK_REQUIRED' }
    $item = Get-Item -LiteralPath $full -Force -ErrorAction Stop
    if ($item.PSIsContainer) { throw 'REGULAR_FILE_REQUIRED' }
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'REPARSE_PATH_FORBIDDEN' }
    for ($ancestor = $item.Directory; $null -ne $ancestor; $ancestor = $ancestor.Parent) {
        if (($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'REPARSE_PATH_FORBIDDEN' }
    }
    $identity = [R6FileIdentity]::Read($full)
    if ($identity.Links -ne 1) { throw 'HARDLINK_ALIAS_FORBIDDEN' }
    return [ordered]@{path=$full; volume=[string]$identity.Volume;
        file_id=('{0:x8}{1:x8}' -f $identity.IndexHigh,$identity.IndexLow)}
}
function Within-Storage([string]$Path) {
    $root = [IO.Path]::GetFullPath($plan.realm.storage_directory).TrimEnd('\') + '\'
    if (-not ([IO.Path]::GetFullPath($Path)).StartsWith($root,[StringComparison]::OrdinalIgnoreCase)) {
        throw 'VM_DISK_OUTSIDE_APPROVED_STORAGE'
    }
}
$diskRecords = @()
$disks = @(Get-VMHardDiskDrive -VM $vm -ErrorAction Stop)
if ($disks.Count -ne @($plan.realm.vhd_paths).Count -or $disks.Count -eq 0) { throw 'EXACT_VM_DISK_SET_REQUIRED' }
foreach ($disk in $disks) {
    $path = Required-Property $disk 'Path'
    if (-not $path -or (Required-Property $disk 'SupportPersistentReservations') -ne $false) { throw 'PASSTHROUGH_OR_SHARED_DISK_FORBIDDEN' }
    Within-Storage $path
    if ($path -cnotin @($plan.realm.vhd_paths)) { throw 'UNAPPROVED_VHD_PATH' }
    $vhd = Get-VHD -Path $path -ErrorAction Stop
    if ($vhd.VhdFormat.ToString() -cne 'VHDX' -or $vhd.VhdType.ToString() -cnotin @('Fixed','Dynamic')
        -or $vhd.ParentPath) { throw 'VHD_FORMAT_OR_PARENT_UNSUPPORTED' }
    $diskRecords += [ordered]@{identity=(Local-FileIdentity $path); format=$vhd.VhdFormat.ToString();
        type=$vhd.VhdType.ToString(); parent=$null; controller_type=$disk.ControllerType.ToString();
        controller_number=$disk.ControllerNumber; controller_location=$disk.ControllerLocation}
}
$baselineIdentity = Local-FileIdentity $plan.baseline.path
$baselineStream = [IO.File]::Open($plan.baseline.path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
try {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $baselineHash = ([BitConverter]::ToString($sha.ComputeHash($baselineStream))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
    if ($baselineHash -cne $plan.baseline.sha256 -or $baselineStream.Length -ne $plan.baseline.size) { throw 'FIXTURE_GENERATOR_BYTES_DIFFER' }
    $baselineAgain = Local-FileIdentity $plan.baseline.path
    if ($baselineAgain.volume -cne $baselineIdentity.volume -or $baselineAgain.file_id -cne $baselineIdentity.file_id) { throw 'FIXTURE_GENERATOR_IDENTITY_CHANGED' }
    $baseline = [ordered]@{origin_kind='immutable_fixture_generator';identity=$baselineIdentity;
        sha256=$baselineHash;size=$baselineStream.Length;installed_package_digest=$plan.baseline.installed_package_digest}
    $worker = $null
    if ($state -ceq 'Running') {
        $workerId = [int](Required-Property $vmSystem 'ProcessID')
        if ($workerId -le 0) { throw 'VM_WORKER_ID_UNAVAILABLE' }
        $process = Get-Process -Id $workerId -ErrorAction Stop
        $worker = [ordered]@{pid=$workerId;creation_time_100ns=$process.StartTime.ToUniversalTime().ToFileTimeUtc();
            image_path=$process.MainModule.FileName;image_sha256=(Get-FileHash -LiteralPath $process.MainModule.FileName -Algorithm SHA256).Hash.ToLowerInvariant()}
    }
    # A second state/worker read catches transition during observation. The
    # supervisor still owns the reconfiguration lock through dispatch/claim.
    $again = Get-VM -Id $vm.Id -ErrorAction Stop
    $againSystem = Get-CimInstance -Namespace 'root/virtualization/v2' -ClassName Msvm_ComputerSystem `
        -Filter ("Name='"+$vm.Id.ToString()+"'") -ErrorAction Stop
    if ($again.State.ToString() -cne $state -or $againSystem.ProcessID -ne $vmSystem.ProcessID) { throw 'VM_CHANGED_DURING_CAPTURE' }
    $payload = [ordered]@{schema_version=1;purpose='hyperv_realm_measurement_v1';
        approved_plan_sha256=$ExpectedPlanSha256;binding_sha256=$ExpectedBindingSha256;
        challenge=$Challenge;kind=$binding.kind;issued_at_ms=$nowMs;
        expires_at_ms=[Math]::Min($nowMs+60000,[long]$plan.expires_at_ms);
        target=$plan.target;realm=$plan.realm;
        profile=[ordered]@{generation=2;state=$state;host_uuid=$hostUuid;
            host_boot_100ns=$os.LastBootUpTime.ToUniversalTime().ToFileTimeUtc();worker=$worker;
            disks=$diskRecords;network_adapters=0;dda=0;gpu_partition=0;fibre_channel=0;checkpoints=0;
            com_pipes=0;dvd_media=0;enabled_integration_services=0;enhanced_session=$false;
            replication_mode=0;control_transport=$plan.control_transport;controller_sid=$controllerSid;
            output_policy='quarantine_vhd_no_export_until_off'};baseline=$baseline}
    $certificate = Get-Item -LiteralPath ('Cert:\LocalMachine\My\'+$CertificateThumbprint) -ErrorAction Stop
    if ((Hash-Bytes $certificate.RawData) -cne $ExpectedCertificateSha256) { throw 'SUPERVISOR_CERTIFICATE_PIN_DIFFERS' }
    $rsa = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($certificate)
    if ($null -eq $rsa) { throw 'SUPERVISOR_PRIVATE_KEY_UNAVAILABLE' }
    try {
        $payloadBytes = $utf8.GetBytes(($payload | ConvertTo-Json -Depth 32 -Compress))
        $signature = $rsa.SignData($payloadBytes,[Security.Cryptography.HashAlgorithmName]::SHA256,
            [Security.Cryptography.RSASignaturePadding]::Pkcs1)
        $envelope = [ordered]@{schema_version=1;algorithm='RS256-PKCS1';
            certificate_sha256=$ExpectedCertificateSha256;payload_b64=[Convert]::ToBase64String($payloadBytes);
            signature_b64=[Convert]::ToBase64String($signature)}
        Publish-New $EnvelopePath $utf8.GetBytes(($envelope | ConvertTo-Json -Compress))
    } finally { $rsa.Dispose(); $certificate.Dispose() }
} finally { $baselineStream.Dispose() }
