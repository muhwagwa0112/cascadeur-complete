# Shared by source and frozen installers. Never imports the incoming runtime.
function Get-CascadeurLocalAppData {
    if ($env:USERPROFILE) {
        $candidate = Join-Path $env:USERPROFILE 'AppData\Local'
        if (Test-Path -LiteralPath $candidate -PathType Container) { return [IO.Path]::GetFullPath($candidate) }
    }
    if (-not $env:LOCALAPPDATA) { throw 'Local AppData is unavailable.' }
    return [IO.Path]::GetFullPath($env:LOCALAPPDATA)
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

function Copy-CascadeurPersistentState([string] $PreviousRuntime, [string] $NextRuntime) {
    $previous = [IO.Path]::GetFullPath($PreviousRuntime).TrimEnd('\')
    $next = [IO.Path]::GetFullPath($NextRuntime).TrimEnd('\')
    if ($previous -ieq $next) { throw 'State migration needs separate runtime directories.' }
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
