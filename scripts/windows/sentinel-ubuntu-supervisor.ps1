# One Windows owner. Optional USB management cannot retire Ubuntu's keepalive.
[CmdletBinding()]
param([switch]$LibraryOnly, [string]$UsbConfigPath, [string]$UsbConfigSha)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ExpectedInstance = $null
$script:ExpectedGuid = $null
$script:Usbipd = $null
$script:UnreapedUsbClient = $null
$script:RuntimeSha = ''
$script:LastUsbFingerprint = ''
$script:UsbErrorSlot = 0

function Limit-SentinelText([object]$Value) {
    $text = [string]$Value
    if ($text.Length -gt 2048) { return $text.Substring(0, 2048) }
    return $text
}

function Get-SentinelBytesSha([byte[]]$Bytes) {
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $hash.Dispose() }
}

function Convert-SentinelError([Management.Automation.ErrorRecord]$Record) {
    $chain = @(); $exception = $Record.Exception
    for ($index = 0; $null -ne $exception -and $index -lt 4; $index++) {
        $native = $null; $nativeExit = $null
        if ($exception -is [ComponentModel.Win32Exception]) { $native = $exception.NativeErrorCode }
        if ($exception.Data.Contains('NativeExitCode')) { $nativeExit = $exception.Data['NativeExitCode'] }
        $chain += @{ type = $exception.GetType().FullName; message = (Limit-SentinelText $exception.Message)
            hresult = $exception.HResult; native_error_code = $native; native_exit_code = $nativeExit
            stack = (Limit-SentinelText $exception.StackTrace) }
        $exception = $exception.InnerException
    }
    return @{ exceptions = $chain; position = (Limit-SentinelText $Record.InvocationInfo.PositionMessage)
        script_stack = (Limit-SentinelText $Record.ScriptStackTrace)
        error_id = (Limit-SentinelText $Record.FullyQualifiedErrorId)
        category = (Limit-SentinelText $Record.CategoryInfo) }
}

function Write-SentinelDocument([string]$Path, [object]$Document, [switch]$Exclusive) {
    $raw = [Text.Encoding]::UTF8.GetBytes(($Document | ConvertTo-Json -Depth 10))
    if ($raw.Length -gt 65536) { throw 'Supervisor diagnostic exceeds64KiB.' }
    $parent = [IO.Path]::GetDirectoryName($Path)
    $folder = Get-Item -LiteralPath $parent -Force
    if (-not $folder.PSIsContainer -or ($folder.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Diagnostic directory differs.' }
    if ($Exclusive) {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
        try { $stream.Write($raw, 0, $raw.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        return
    }
    $temporary = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    try {
        $stream = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $stream.Write($raw, 0, $raw.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        if (Test-Path -LiteralPath $Path) {
            $before = Get-Item -LiteralPath $Path -Force
            if ($before.PSIsContainer -or ($before.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Diagnostic target differs.' }
            [IO.File]::Replace($temporary, $Path, [Management.Automation.Language.NullString]::Value)
        } else { [IO.File]::Move($temporary, $Path) }
    } finally { if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) } }
}

function Write-SentinelUsbError([Management.Automation.ErrorRecord]$Record) {
    try {
        $errorDocument = Convert-SentinelError $Record
        $fingerprint = Get-SentinelBytesSha ([Text.Encoding]::UTF8.GetBytes(($errorDocument | ConvertTo-Json -Depth 10 -Compress)))
        if ($fingerprint -ceq $script:LastUsbFingerprint) { return }
        $script:LastUsbFingerprint = $fingerprint
        $slot = $script:UsbErrorSlot; $script:UsbErrorSlot = ($slot + 1) % 8
        $document = @{ schema = 'sentinel.usb-supervision-error/1'; observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
            windows_pid = $PID; runtime_sha256 = $script:RuntimeSha; fingerprint = $fingerprint
            errors = @($errorDocument); primary_runtime_action = 'KEEP_RUNNING'; restart_calls = 0 }
        Write-SentinelDocument (Join-Path $PSScriptRoot ('usb-error-slot-' + $slot + '.json')) $document
    } catch { } # Diagnostic storage is outside primary-runtime authority.
}

function Write-SentinelPrimaryError([Management.Automation.ErrorRecord]$Record) {
    try {
        $existing = @(Get-ChildItem -LiteralPath $PSScriptRoot -File -Filter 'primary-error-*.json')
        if ($existing.Count -ge 8) { return } # Preserve the first eight original failures.
        $document = @{ schema = 'sentinel.supervisor-primary-error/1'; returned_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
            exit_code = 1; windows_pid = $PID; runtime = $PSCommandPath; runtime_sha256 = $script:RuntimeSha
            errors = @((Convert-SentinelError $Record)); diagnostic_only = $true; restart_calls = 0 }
        Write-SentinelDocument (Join-Path $PSScriptRoot ('primary-error-' + [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N') + '.json')) $document -Exclusive
    } catch { }
}

function Write-SentinelCurrentState([Diagnostics.Process]$Anchor, [int]$Iterations, [string]$UsbState) {
    try {
        $document = @{ schema = 'sentinel.ubuntu-supervisor-state/1'; observed_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
            windows_pid = $PID; anchor_pid = $Anchor.Id; runtime_sha256 = $script:RuntimeSha
            primary = 'RUNNING'; iterations = $Iterations; usb = $UsbState; restart_calls = 0 }
        Write-SentinelDocument (Join-Path $PSScriptRoot 'supervisor-v3-state.json') $document
    } catch { }
}

function Set-SentinelUsbConfiguration([string]$Path, [string]$ExpectedSha) {
    if ($ExpectedSha -cnotmatch '^[a-f0-9]{64}$' -or [string]::IsNullOrEmpty($Path)) { throw 'Exact USB configuration hash/path is required.' }
    $full = [IO.Path]::GetFullPath($Path)
    if ([IO.Path]::GetDirectoryName($full) -ine [IO.Path]::GetFullPath($PSScriptRoot) -or
        [IO.Path]::GetFileName($full) -cne ('usb-binding-' + $ExpectedSha + '.json')) { throw 'USB configuration is outside its immutable installation.' }
    $file = Get-Item -LiteralPath $full -Force
    if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or $file.Length -gt 8192) { throw 'USB configuration file differs.' }
    $raw = [IO.File]::ReadAllBytes($full)
    if ($raw.Length -gt 8192 -or (Get-SentinelBytesSha $raw) -cne $ExpectedSha) { throw 'USB configuration hash differs.' }
    $text = [Text.Encoding]::UTF8.GetString($raw)
    $config = $text | ConvertFrom-Json
    $names = @($config.PSObject.Properties.Name)
    if ($names.Count -ne 3 -or (@($names | Sort-Object) -join ',') -cne 'instance_id,persisted_guid,schema') { throw 'USB configuration shape differs.' }
    foreach ($name in @('schema', 'instance_id', 'persisted_guid')) {
        if ([regex]::Matches($text, ('"' + $name + '"\s*:')).Count -ne 1) { throw 'Duplicate USB configuration member.' }
    }
    if ($config.schema -cne 'sentinel.ubuntu-usb-binding/1' -or $config.instance_id -isnot [string] -or
        $config.instance_id -cnotmatch '^USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}\\[A-Za-z0-9_&+.-]+$' -or
        $config.persisted_guid -isnot [string]) { throw 'USB configuration identity is invalid.' }
    $guid = [guid]::Empty
    if (-not [guid]::TryParseExact($config.persisted_guid, 'D', [ref]$guid)) { throw 'USB persisted identity is invalid.' }
    $script:ExpectedInstance = $config.instance_id
    $script:ExpectedGuid = $guid.ToString('D')
}

function Get-SentinelUsbDecision([object]$Document) {
    if ($null -eq $Document -or $null -eq $Document.PSObject.Properties['Devices'] -or $Document.Devices -isnot [array]) { throw 'USB state has no device inventory array.' }
    $devices = @($Document.Devices)
    if ($devices.Count -gt 256) { throw 'USB inventory exceeds the admitted bound.' }
    $related = @($devices | Where-Object {
        $null -ne $_ -and
        (($null -ne $_.PSObject.Properties['InstanceId'] -and $_.InstanceId -ceq $script:ExpectedInstance) -or
         ($null -ne $_.PSObject.Properties['PersistedGuid'] -and $_.PersistedGuid -eq $script:ExpectedGuid))
    })
    if ($related.Count -eq 0) { return [pscustomobject]@{ Kind = 'ABSENT'; BusId = $null } }
    if ($related.Count -ne 1) { throw 'USB identity is ambiguous.' }
    $device = $related[0]
    if ($null -eq $device.PSObject.Properties['InstanceId'] -or $null -eq $device.PSObject.Properties['PersistedGuid']) { throw 'USB identity fields are absent.' }
    if ($device.InstanceId -isnot [string] -or $device.InstanceId -cne $script:ExpectedInstance -or $device.PersistedGuid -isnot [string] -or $device.PersistedGuid -ne $script:ExpectedGuid) { throw 'USB serial or persisted sharing identity changed.' }
    if ($null -eq $device.PSObject.Properties['BusId'] -or $null -eq $device.PSObject.Properties['ClientIPAddress']) { throw 'USB state fields are absent.' }
    if ($null -eq $device.BusId) {
        if ($null -ne $device.ClientIPAddress) { throw 'Unplugged USB state has a client.' }
        return [pscustomobject]@{ Kind = 'ABSENT'; BusId = $null }
    }
    if ($device.BusId -isnot [string] -or $device.BusId -cnotmatch '^[1-9][0-9]*-[1-9][0-9]*$') { throw 'USB bus identity is invalid.' }
    if ($null -ne $device.ClientIPAddress) {
        $address = $null
        if ($device.ClientIPAddress -isnot [string] -or -not [Net.IPAddress]::TryParse($device.ClientIPAddress, [ref]$address)) { throw 'USB client address is invalid.' }
        return [pscustomobject]@{ Kind = 'ATTACHED'; BusId = $device.BusId }
    }
    return [pscustomobject]@{ Kind = 'ATTACH'; BusId = $device.BusId }
}

function Invoke-SentinelUsbStep([scriptblock]$Observe, [scriptblock]$Attach) {
    $first = Get-SentinelUsbDecision (& $Observe)
    if ($first.Kind -ne 'ATTACH') { return $first.Kind }
    $fresh = Get-SentinelUsbDecision (& $Observe)
    if ($fresh.Kind -ne 'ATTACH' -or $fresh.BusId -cne $first.BusId) { return 'REOBSERVE' }
    $result = & $Attach $fresh.BusId
    $after = Get-SentinelUsbDecision (& $Observe)
    if ($null -eq $result -or $null -eq $result.PSObject.Properties['ExitCode']) { throw 'USB attach result is invalid.' }
    if ($after.Kind -eq 'ATTACH') { throw ('Exact USB attachment did not complete; exit=' + $result.ExitCode) }
    return $after.Kind
}

function Stop-SentinelOwnedClientTree([Diagnostics.Process]$Process) {
    if ($Process.HasExited) { return }
    $ownedId = $Process.Id
    $killer = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\taskkill.exe') -ArgumentList ('/PID ' + $ownedId + ' /T /F') -WindowStyle Hidden -PassThru
    try {
        if (-not $killer.WaitForExit(5000)) { throw 'Owned USB client tree cleanup timed out.' }
        if ($killer.ExitCode -ne 0) { throw 'Owned USB client tree cleanup command refused or failed.' }
        if (-not $Process.WaitForExit(5000)) { throw 'Owned USB client tree cleanup was not confirmed.' }
    } finally {
        if (-not $killer.HasExited) { $killer.Kill(); $null = $killer.WaitForExit(5000) }
        $killer.Dispose()
    }
}

function Invoke-SentinelUsbipd([string]$Arguments, [int]$TimeoutSeconds = 15) {
    if ($null -ne $script:UnreapedUsbClient) {
        if (-not $script:UnreapedUsbClient.HasExited) { throw 'Prior owned USB client cleanup is unconfirmed; USB management deferred.' }
        $script:UnreapedUsbClient.Dispose(); $script:UnreapedUsbClient = $null
    }
    $usbFile = Get-Item -LiteralPath $script:Usbipd -Force
    if ($usbFile.PSIsContainer -or ($usbFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $usbFile.VersionInfo.ProductVersion -cnotmatch '^5\.3\.0(?:$|[-+.])') { throw 'The admitted usbipd-win5.3.0 client is unavailable.' }
    if ($null -eq ([Management.Automation.PSTypeName]'SentinelBoundedUsbReaderV1').Type) {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Threading.Tasks;
public static class SentinelBoundedUsbReaderV1 {
    public static Task<string> Read(StreamReader reader, int maximum) {
        return Task.Run(() => {
            var result = new StringBuilder(); var buffer = new char[4096]; int count;
            while ((count = reader.Read(buffer, 0, buffer.Length)) != 0) {
                if (result.Length + count > maximum)
                    throw new InvalidOperationException("USB client output exceeds the admitted bound.");
                result.Append(buffer, 0, count);
            }
            return result.ToString();
        });
    }
}
'@
    }
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $script:Usbipd; $info.Arguments = $Arguments
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process; $process.StartInfo = $info
    $started = $false; $originalFailure = $null
    try {
        $watch = [Diagnostics.Stopwatch]::StartNew()
        if (-not $process.Start()) { throw 'Could not start the exact USB client.' }
        $started = $true
        $outTask = [SentinelBoundedUsbReaderV1]::Read($process.StandardOutput, 1MB)
        $errTask = [SentinelBoundedUsbReaderV1]::Read($process.StandardError, 16KB)
        $remaining = [int]($TimeoutSeconds * 1000 - $watch.ElapsedMilliseconds)
        if ($remaining -le 0 -or -not $process.WaitForExit($remaining)) { throw 'Exact USB client timed out.' }
        $remaining = [int]($TimeoutSeconds * 1000 - $watch.ElapsedMilliseconds)
        if ($remaining -le 0 -or -not [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($outTask, $errTask), $remaining)) { throw 'Exact USB client output timed out.' }
        $stdout = $outTask.GetAwaiter().GetResult(); $stderr = $errTask.GetAwaiter().GetResult()
        if ($stdout.Length -gt 1MB -or $stderr.Length -gt 16KB) { throw 'USB client output exceeds the admitted bound.' }
        return [pscustomobject]@{ ExitCode = $process.ExitCode; Stdout = $stdout; Stderr = $stderr }
    } catch { $originalFailure = $_; throw }
    finally {
        if ($started -and -not $process.HasExited) {
            try { Stop-SentinelOwnedClientTree $process }
            catch { if ($null -ne $originalFailure) { Write-SentinelUsbError $_ } }
            if (-not $process.HasExited) { $script:UnreapedUsbClient = $process; $process = $null }
        }
        if ($null -ne $process) { $process.Dispose() }
    }
}

function Get-SentinelUsbState {
    $result = Invoke-SentinelUsbipd 'state'
    if ($result.ExitCode -ne 0) {
        $failure = New-Object -TypeName System.InvalidOperationException -ArgumentList 'Exact USB state observation failed.'
        $failure.Data['NativeExitCode'] = $result.ExitCode
        throw $failure
    }
    return ($result.Stdout | ConvertFrom-Json)
}

function Invoke-SentinelOptionalUsb([scriptblock]$Operation) {
    try { return (& $Operation) }
    catch { try { Write-SentinelUsbError $_ } catch { }; return 'UNAVAILABLE' }
}

if ($LibraryOnly) { return }
$anchor = $null
try {
    $file = Get-Item -LiteralPath $PSCommandPath -Force
    $script:RuntimeSha = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
        $file.Name -cne ('startup-' + $script:RuntimeSha + '.ps1')) { throw 'Startup runtime hash/path differs.' }
    $wsl = Join-Path $env:SystemRoot 'System32\wsl.exe'
    $anchor = Start-Process -FilePath $wsl -ArgumentList '-d Ubuntu -u bron --exec /usr/bin/sleep infinity' -WindowStyle Hidden -PassThru
    $iterations = 0
    Write-SentinelCurrentState $anchor $iterations 'STARTING'
    while ($true) {
        if ($anchor.HasExited) {
            $failure = New-Object -TypeName System.InvalidOperationException -ArgumentList ('Foreground Ubuntu request exited unexpectedly; exit=' + $anchor.ExitCode)
            $failure.Data['NativeExitCode'] = $anchor.ExitCode
            throw $failure
        }
        $usbState = Invoke-SentinelOptionalUsb {
            Set-SentinelUsbConfiguration $UsbConfigPath $UsbConfigSha
            $script:Usbipd = Join-Path $env:ProgramFiles 'usbipd-win\usbipd.exe'
            Invoke-SentinelUsbStep -Observe { Get-SentinelUsbState } -Attach {
                param([string]$BusId)
                if ($BusId -cnotmatch '^[1-9][0-9]*-[1-9][0-9]*$') { throw 'Refusing invalid USB bus.' }
                Invoke-SentinelUsbipd ('attach --wsl Ubuntu --busid ' + $BusId) 90
            }
        }
        if ($anchor.HasExited) {
            $failure = New-Object -TypeName System.InvalidOperationException -ArgumentList ('Foreground Ubuntu request exited during optional USB work; exit=' + $anchor.ExitCode)
            $failure.Data['NativeExitCode'] = $anchor.ExitCode
            throw $failure
        }
        $iterations++
        Write-SentinelCurrentState $anchor $iterations $usbState
        Start-Sleep -Seconds 5
    }
} catch {
    Write-SentinelPrimaryError $_
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
} finally {
    if ($null -ne $script:UnreapedUsbClient) {
        try { if (-not $script:UnreapedUsbClient.HasExited) { Stop-SentinelOwnedClientTree $script:UnreapedUsbClient } } catch { }
        try { $script:UnreapedUsbClient.Dispose() } catch { }
    }
    if ($null -ne $anchor) {
        try { if (-not $anchor.HasExited) { $anchor.Kill(); $anchor.WaitForExit() } }
        finally { $anchor.Dispose() }
    }
}
