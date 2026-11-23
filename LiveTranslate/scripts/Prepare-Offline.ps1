[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetDirectoryName($PSScriptRoot)
$payload = Join-Path $root 'payload'
$reports = Join-Path $root 'model-test-results'
$runtime = Join-Path $root 'runtime'
$indexFile = Join-Path $payload 'checked-files.json'
$lock = $null
$stage = $null
$result = 1

function Get-Digest([string]$File) {
    $stream = [IO.File]::OpenRead($File)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose(); $stream.Dispose() }
}

function Get-ChildFile([string]$Parent,[string]$Name) {
    if ([IO.Path]::IsPathRooted($Name) -or $Name -match '(^|[/\\])\.\.([/\\]|$)' -or $Name.Contains(':')) {
        throw 'Invalid relative path in the offline manifest.'
    }
    $path = [IO.Path]::GetFullPath((Join-Path $Parent $Name))
    if (-not $path.StartsWith(($Parent.TrimEnd('\')+'\'),[StringComparison]::OrdinalIgnoreCase)) {
        throw 'A bundle file resolves outside its destination.'
    }
    return $path
}

function Test-RegularFile([string]$Path,[long]$Bytes,[string]$Hash) {
    if (-not [IO.File]::Exists($Path)) { return $false }
    $info = [IO.FileInfo]::new($Path)
    if (($info.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $info.Length -ne $Bytes) { return $false }
    return (Get-Digest $Path) -ceq $Hash
}

try {
    [IO.Directory]::CreateDirectory($reports) | Out-Null
    try { $lock = [IO.File]::Open((Join-Path $reports 'offline-setup.lock'),'OpenOrCreate','ReadWrite','None') }
    catch [IO.IOException] { throw 'Another setup may be running. Close it or let it finish, then open LiveTranslate.exe again.' }
    if ((Get-Digest $indexFile) -cne '43c2c21bc9c17193281ead02f05298a2d742beea9f85771835366eb20f5c29b6') { throw 'The offline file list changed. Extract a fresh copy of the ZIP.' }
    $bundle = [IO.File]::ReadAllText($indexFile) | ConvertFrom-Json
    Write-Host 'Checking the included offline files...'
    foreach ($file in $bundle.payload) {
        $path = Get-ChildFile $payload $file.name
        if (-not (Test-RegularFile $path $file.bytes $file.sha256)) { throw ('Missing or changed payload file: '+$file.name) }
    }
    $runtimeFiles = [Collections.Generic.List[object]]::new()
    foreach ($name in $bundle.runtime_indexes) {
        $description = [IO.File]::ReadAllText((Get-ChildFile $payload $name)) | ConvertFrom-Json
        foreach ($entry in $description.members.PSObject.Properties) {
            $runtimeFiles.Add([pscustomobject]@{name=$entry.Name;bytes=$entry.Value.bytes;sha256=$entry.Value.sha256})
        }
    }
    $existing = [IO.Directory]::Exists($runtime)
    $missing = [Collections.Generic.List[object]]::new()
    $visited = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($file in $runtimeFiles) {
        $dest = Get-ChildFile $runtime $file.name
        if ($existing) {
            $parent = [IO.Path]::GetDirectoryName($dest)
            while ($parent -and $parent.Length -ge $runtime.Length -and $visited.Add($parent)) {
                if ([IO.Directory]::Exists($parent) -and ([IO.File]::GetAttributes($parent) -band [IO.FileAttributes]::ReparsePoint)) { throw 'The runtime contains a redirected folder. Extract into a new folder.' }
                $parent = [IO.Path]::GetDirectoryName($parent)
            }
        }
        if (-not [IO.File]::Exists($dest)) { $missing.Add($file); continue }
        if (-not (Test-RegularFile $dest $file.bytes $file.sha256)) {
            throw ('An existing runtime file differs: '+$file.name+'. Extract into a new folder to keep both copies.')
        }
    }
    if ($missing.Count) {
        $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
        if (-not [IO.File]::Exists($tar)) { throw 'The Windows 11 tar.exe utility is unavailable.' }
        $stage = Join-Path $root ('.lt-'+[Guid]::NewGuid().ToString('N').Substring(0,8))
        [IO.Directory]::CreateDirectory($stage) | Out-Null
        Write-Host 'Unpacking the Windows runtime...'
        Push-Location -LiteralPath $root
        try {
            foreach ($name in $bundle.runtime_archives) {
                # Keep native tar arguments ASCII even under a CJK Windows profile.
                & $tar -xf ('payload\'+$name) -C ([IO.Path]::GetFileName($stage))
                if ($LASTEXITCODE -ne 0) { throw 'Windows could not unpack the runtime. Use a shorter writable folder and retry.' }
            }
        } finally { Pop-Location }
        foreach ($file in $runtimeFiles) {
            if (-not (Test-RegularFile (Get-ChildFile $stage $file.name) $file.bytes $file.sha256)) {
                throw ('Unpacked runtime verification failed: '+$file.name)
            }
        }
        if (-not $existing) {
            [IO.Directory]::Move($stage,$runtime)
            $stage = $null
        } else {
            # All existing members have already matched. Install only absent files.
            foreach ($file in $missing) {
                $dest = Get-ChildFile $runtime $file.name
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($dest)) | Out-Null
                [IO.File]::Move((Get-ChildFile $stage $file.name),$dest)
            }
        }
    }
    $env:HF_HUB_OFFLINE = '1'
    $env:HF_HUB_DISABLE_TELEMETRY = '1'
    $env:PYTHONUTF8 = '1'
    Write-Host 'Preparing the 13 original language files...'
    & (Join-Path $runtime 'python.exe') -I -B (Join-Path $payload 'restore_models.py') --app $root
    if ($LASTEXITCODE -ne 0) { throw 'The included model files could not be restored. Read the preceding message.' }
    # Keep folder names such as "%TEMP%" out of cmd's own variable expansion.
    Push-Location -LiteralPath $root
    try {
        $commandShell = Join-Path $env:SystemRoot 'System32\cmd.exe'
        & $commandShell --% /d /v:off /s /c ""scripts\Download and test models.cmd" --offline --non-interactive"
        if ($LASTEXITCODE -ne 0) { throw 'Local verification did not complete. Read model-test-results\last-run.txt and retry.' }
    } finally { Pop-Location }
    $marker = Join-Path $reports 'offline-43c2c21bc9c17193.ok'
    [IO.File]::WriteAllText($marker,'43c2c21bc9c17193281ead02f05298a2d742beea9f85771835366eb20f5c29b6')
    $result = 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
} finally {
    if ($null -ne $stage -and [IO.Directory]::Exists($stage)) {
        $resolved = [IO.Path]::GetFullPath($stage)
        if ([IO.Path]::GetDirectoryName($resolved) -eq $root -and
            [IO.Path]::GetFileName($resolved) -match '^\.lt-[0-9a-f]{8}$' -and
            -not ([IO.File]::GetAttributes($resolved) -band [IO.FileAttributes]::ReparsePoint)) {
            [IO.Directory]::Delete($resolved,$true)
        }
    }
    if ($lock) { $lock.Dispose() }
}
exit $result
