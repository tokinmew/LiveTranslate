# Windows PowerShell 5.1. Only model-sources.json supplies download URLs and identities.
[CmdletBinding()]
param([switch]$Offline)
$ErrorActionPreference = 'Stop'
$kitRoot = [IO.Path]::GetDirectoryName($PSScriptRoot)
$resultsDir = Join-Path $kitRoot 'model-test-results'
$utf8 = New-Object Text.UTF8Encoding($false)
$hfDelivery = @('huggingface.co','cdn-lfs.huggingface.co','cdn-lfs.hf.co','cdn-lfs-us-1.hf.co',
    'cdn-lfs-eu-1.hf.co','cas-bridge.xethub.hf.co','us.aws.cdn.hf.co','us.gcp.cdn.hf.co')
$allowedSpeech = @('config.json','model.bin','tokenizer.json','vocabulary.txt')
$allowedOcr = @('chi_sim','chi_tra','kor','jpn','jpn_vert')
$allowedText = @('zt','zh','ko','ja')
$speechRevision = 'ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66'
$speechTreeUrl = 'https://huggingface.co/api/models/Systran/faster-whisper-base/tree/' + $speechRevision
$metadataNames = @('config.json','tokenizer.json','vocabulary.txt')

function Assert-ModelUri([Uri]$Uri, [string]$Kind, [bool]$Initial) {
    if (!$Uri.IsAbsoluteUri -or $Uri.Scheme -ne 'https' -or $Uri.Port -ne 443 -or $Uri.UserInfo -or $Uri.Fragment) {
        throw 'A model URI has an invalid protocol, port or authority.'
    }
    if ($Kind -eq 'ocr') {
        if ($Uri.IdnHost -ne 'raw.githubusercontent.com') { throw 'Refused a non-approved OCR host.' }
    } elseif (($Initial -and $Uri.IdnHost -ne 'huggingface.co') -or ($hfDelivery -notcontains $Uri.IdnHost)) {
        throw 'Refused a non-approved model delivery host.'
    }
}

function Get-Target([object]$Item) {
    $name = [string]$Item.name
    switch -CaseSensitive ([string]$Item.kind) {
        'text' {
            if ($allowedText -cnotcontains [string]$Item.language -or $name -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,100}\.argosmodel$') { throw 'Unknown text pack.' }
            return Join-Path $kitRoot ('data\reviewed-packs\' + $name)
        }
        'speech' {
            if ($allowedSpeech -cnotcontains $name) { throw 'Unknown speech asset.' }
            return Join-Path $kitRoot ('data\speech\base\' + $name)
        }
        'ocr' {
            if ($name -cnotmatch '^([a-z_]+)\.traineddata$' -or $allowedOcr -cnotcontains [IO.Path]::GetFileNameWithoutExtension($name)) { throw 'Unknown OCR asset.' }
            return Join-Path $kitRoot ('data\tessdata\' + $name)
        }
        default { throw 'Unknown model kind.' }
    }
}

function Get-Limit([object]$Item) {
    if ($Item.kind -eq 'ocr' -or ($Item.kind -eq 'speech' -and $Item.name -ne 'model.bin')) { return 64MB }
    return 512MB
}

function Check-Manifest([object[]]$Files) {
    $seen = @{}
    $textCodes = @{}
    if ($Files.Count -ne 13) { throw 'Expected four text archives, five OCR files, and four speech files.' }
    foreach ($item in $Files) {
        $target = Get-Target $item
        if ($seen.ContainsKey($target)) { throw 'Duplicate destination in model-sources.json.' }
        $seen[$target] = $true
        if ($item.kind -eq 'text') {
            if ($textCodes.ContainsKey([string]$item.language)) { throw 'Duplicate text language.' }
            $textCodes[[string]$item.language] = $true
        }
        Assert-ModelUri ([Uri]$item.url) $item.kind $true
        if ($item.sha256 -and [string]$item.sha256 -notmatch '^[0-9a-fA-F]{64}$') { throw 'Invalid SHA-256 identity.' }
        if ($item.git_blob_sha1 -and [string]$item.git_blob_sha1 -notmatch '^[0-9a-fA-F]{40}$') { throw 'Invalid Git blob identity.' }
        if (!$item.sha256 -and !$item.git_blob_sha1) {
            $assetPath = '/Systran/faster-whisper-base/resolve/' + $speechRevision + '/' + $item.name
            if ($item.kind -ne 'speech' -or $metadataNames -cnotcontains $item.name -or
                [string]$item.metadata_url -cne $speechTreeUrl -or ([Uri]$item.url).AbsolutePath -cne $assetPath) {
                throw 'A source is missing a pinned digest or its approved commit-specific speech tree lookup.'
            }
        }
        if ($null -ne $item.bytes -and ([long]$item.bytes -le 0 -or [long]$item.bytes -gt (Get-Limit $item))) { throw 'Invalid model byte size.' }
    }
}

function Read-TreeResponse([object]$Client) {
    # This endpoint is fixed and delivers small metadata JSON. Follow no redirects.
    $timeout = New-Object Threading.CancellationTokenSource
    $timeout.CancelAfter([TimeSpan]::FromSeconds(45))
    try {
        $response = $Client.GetAsync([Uri]$speechTreeUrl,[Net.Http.HttpCompletionOption]::ResponseHeadersRead,$timeout.Token).GetAwaiter().GetResult()
        try {
            if ([int]$response.StatusCode -ne 200) { throw ('The official speech tree returned HTTP ' + [int]$response.StatusCode + '.') }
            if ($response.Content.Headers.ContentLength -gt 256KB) { throw 'Speech tree metadata exceeds its size limit.' }
            $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            $memory = New-Object IO.MemoryStream
            try {
                $block = New-Object byte[] 8192
                while (($n=$stream.ReadAsync($block,0,$block.Length,$timeout.Token).GetAwaiter().GetResult()) -gt 0) {
                    if ($memory.Length + $n -gt 256KB) { throw 'Speech tree metadata exceeds its size limit.' }
                    $memory.Write($block,0,$n)
                }
                return $utf8.GetString($memory.ToArray())
            } finally { $memory.Dispose(); $stream.Dispose() }
        } finally { $response.Dispose() }
    } finally { $timeout.Dispose() }
}

function Resolve-TreeEntry([object[]]$Tree, [object]$Item) {
    $matchesForFile = @($Tree | Where-Object { $_.path -ceq $Item.name -and $_.type -ceq 'file' })
    if ($matchesForFile.Count -ne 1) { throw 'The reviewed file is missing or duplicated in the speech repository tree.' }
    $entry = $matchesForFile[0]
    $size = [long]$entry.size
    if ($size -le 0 -or $size -gt (Get-Limit $Item) -or ($null -ne $Item.bytes -and $size -ne [long]$Item.bytes)) {
        throw 'Speech tree byte length is invalid or conflicts with the reviewed manifest.'
    }
    if ($null -ne $entry.lfs) {
        $hash = [string]$entry.lfs.oid
        if (!$hash) { $hash = [string]$entry.lfs.sha256 }
        if ($hash -notmatch '^[0-9a-fA-F]{64}$' -or ($entry.lfs.size -and [long]$entry.lfs.size -ne $size)) {
            throw 'The speech tree LFS identity or size is invalid.'
        }
        $Item | Add-Member NoteProperty sha256 $hash -Force
    } else {
        if ([string]$entry.oid -notmatch '^[0-9a-fA-F]{40}$') { throw 'The speech tree returned an invalid Git blob identity.' }
        $Item | Add-Member NoteProperty git_blob_sha1 ([string]$entry.oid) -Force
    }
    $Item | Add-Member NoteProperty bytes $size -Force
}

function Read-SpeechTree([object]$Client, [bool]$LocalOnly) {
    $cache = Join-Path $resultsDir ('speech-tree-' + $speechRevision + '.dpapi')
    Add-Type -AssemblyName System.Security
    $scope = [Security.Cryptography.DataProtectionScope]::CurrentUser
    $purpose = $utf8.GetBytes($speechTreeUrl)
    if ($LocalOnly) {
        if (![IO.File]::Exists($cache)) { throw 'Offline speech metadata is missing. Run one online file check to cache the official pinned tree for this Windows account.' }
        if (([IO.FileInfo]$cache).Length -gt 512KB) { throw 'Cached speech metadata is too large.' }
        $json = $utf8.GetString([Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($cache),$purpose,$scope))
    } else {
        $json = Read-TreeResponse $Client
    }
    $tree = ConvertFrom-Json -InputObject $json
    if ($tree -isnot [Array] -or !$tree.Count -or $tree.Count -gt 512) { throw 'Unexpected speech model tree format.' }
    if (!$LocalOnly) {
        # Bind the locally cached HTTPS response to this commit and Windows account.
        # A cache error leaves the current online verification usable.
        try {
            $protected = [Security.Cryptography.ProtectedData]::Protect($utf8.GetBytes($json),$purpose,$scope)
            [IO.File]::WriteAllBytes($cache,$protected)
        } catch { Write-Host 'The pinned speech tree could not be cached. A later offline check will need a usable cache.' }
    }
    return $tree
}

function Assert-SafeDirectory([string]$Folder) {
    $folderPath = [IO.Path]::GetFullPath($Folder)
    if ($folderPath -eq $kitRoot) { return }
    if (!$folderPath.StartsWith($kitRoot + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Asset path left the kit directory.' }
    Assert-SafeDirectory ([IO.Path]::GetDirectoryName($folderPath))
    if ([IO.Directory]::Exists($folderPath)) {
        if (([IO.File]::GetAttributes($folderPath) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Model folders must not be links.' }
    } else { [void][IO.Directory]::CreateDirectory($folderPath) }
}

function Find-Scanner {
    $platforms = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'Microsoft\Windows Defender\Platform'
    if ([IO.Directory]::Exists($platforms)) {
        $candidates = Get-ChildItem -LiteralPath $platforms -Directory | Where-Object { $_.Name -match '^\d+\.\d+\.\d+\.\d+-\d+$' } |
            Sort-Object { [Version](($_.Name -split '-')[0]) } -Descending
        foreach ($folder in $candidates) {
            $path = Join-Path $folder.FullName 'MpCmdRun.exe'
            if ([IO.File]::Exists($path)) { return $path }
        }
    }
    $fallback = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'Windows Defender\MpCmdRun.exe'
    if ([IO.File]::Exists($fallback)) { return $fallback }
    throw 'Microsoft Defender command-line scanner was not found. No models can be approved.'
}

function Invoke-FileScan([string]$Scanner, [string]$File) {
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $Scanner
    $start.Arguments = '-Scan -ScanType 3 -File "' + $File + '" -DisableRemediation'
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $start.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (!$process.WaitForExit(600000)) { try { $process.Kill() } catch { }; throw 'Defender scan timed out.' }
        $output = $stdout.Result + [Environment]::NewLine + $stderr.Result
        if ($process.ExitCode -ne 0) { throw ('Defender scan failed or detected a threat (exit ' + $process.ExitCode + '). Inspect Windows Security Protection history.') }
        # Unknown or localized output remains unapproved, including a zero exit without an explicit clean verdict.
        $fileVerdict = '(?im)^Scanning[ \t]+"?' + [regex]::Escape($File) + '"?[ \t]+found no threats[.!]?[ \t]*\r?$'
        if ($output -notmatch $fileVerdict) {
            throw 'Defender did not return a recognizable English clean-file verdict. The asset remains unapproved.'
        }
    } finally { $process.Dispose() }
}

function Save-Download([object]$Client, [object]$Item, [string]$OutFile) {
    $uri = [Uri]$Item.url
    $maxBytes = Get-Limit $Item
    if ($null -ne $Item.bytes) { $maxBytes = [long]$Item.bytes }
    $deadline = New-Object Threading.CancellationTokenSource
    $deadline.CancelAfter([TimeSpan]::FromMinutes(20))
    try {
        for ($hop = 0; $hop -le 8; $hop++) {
            Assert-ModelUri $uri $Item.kind ($hop -eq 0)
            $response = $Client.GetAsync($uri, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $deadline.Token).GetAwaiter().GetResult()
            try {
                $status = [int]$response.StatusCode
                if ($status -in 301,302,303,307,308) {
                    if ($null -eq $response.Headers.Location) { throw 'Missing redirect destination.' }
                    $uri = New-Object Uri($uri, $response.Headers.Location)
                    continue
                }
                if ($status -ne 200) { throw ('Download service returned HTTP ' + $status + '.') }
                $declared = $response.Content.Headers.ContentLength
                if ($null -ne $declared -and ($declared -gt $maxBytes -or ($null -ne $Item.bytes -and $declared -ne [long]$Item.bytes))) { throw 'Download length differs from reviewed size or exceeds limit.' }
                $inputBytes = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                $outBytes = [IO.File]::Open($OutFile, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
                try {
                    $buffer = New-Object byte[] (256KB)
                    $size = [long]0
                    while (($n = $inputBytes.ReadAsync($buffer,0,$buffer.Length,$deadline.Token).GetAwaiter().GetResult()) -gt 0) {
                        $size += $n
                        if ($size -gt $maxBytes) { throw 'Download exceeded reviewed size or limit.' }
                        $outBytes.Write($buffer,0,$n)
                    }
                    if ($size -eq 0 -or ($null -ne $declared -and $size -ne $declared)) { throw 'Download ended before the complete body arrived.' }
                } finally { $outBytes.Dispose(); $inputBytes.Dispose() }
                return
            } finally { $response.Dispose() }
        }
        throw 'Too many download redirects.'
    } finally { $deadline.Dispose() }
}

function Test-Asset([string]$File, [object]$Item, [string]$Scanner) {
    if (([IO.File]::GetAttributes($File) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Model files must not be links.' }
    $stream = [IO.File]::Open($File,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $length = $stream.Length
        if ($length -le 0 -or $length -gt (Get-Limit $Item) -or ($null -ne $Item.bytes -and $length -ne [long]$Item.bytes)) { throw 'File size differs from the reviewed asset or exceeds the limit.' }
        $digest = [BitConverter]::ToString($sha256.ComputeHash($stream)).Replace('-','').ToLowerInvariant()
        if ($Item.sha256 -and $digest -ne $Item.sha256) { throw 'SHA-256 mismatch.' }
        if ($Item.git_blob_sha1) {
            $git = [Security.Cryptography.SHA1]::Create()
            try {
                $stream.Position = 0
                $prefix = [Text.Encoding]::ASCII.GetBytes(('blob {0}' -f $length) + [char]0)
                [void]$git.TransformBlock($prefix,0,$prefix.Length,$prefix,0)
                $chunk = New-Object byte[] (256KB)
                while (($n = $stream.Read($chunk,0,$chunk.Length)) -gt 0) { [void]$git.TransformBlock($chunk,0,$n,$chunk,0) }
                [void]$git.TransformFinalBlock($chunk,0,0)
                if ([BitConverter]::ToString($git.Hash).Replace('-','') -ne $Item.git_blob_sha1) { throw 'Git blob digest mismatch.' }
            } finally { $git.Dispose() }
        }
        Invoke-FileScan $Scanner $File
        return @{ sha256=$digest; bytes=$length }
    } finally { $sha256.Dispose(); $stream.Dispose() }
}

function Main {
    Assert-SafeDirectory $resultsDir
    $reportFile = Join-Path $resultsDir 'model-file-checks.json'
    $records = New-Object Collections.Generic.List[object]
    $report = [ordered]@{status='running'; started=[DateTime]::UtcNow.ToString('o'); files=@()}
    $http = $null
    $guard = $null
    try {
        $guard = [IO.File]::Open((Join-Path $resultsDir 'model-fetch.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
        [IO.File]::WriteAllText($reportFile,($report | ConvertTo-Json -Depth 5),$utf8)
        $manifest = [IO.File]::ReadAllText((Join-Path $kitRoot 'config\model-sources.json'),$utf8) | ConvertFrom-Json
        $items = @($manifest.files)
        Check-Manifest $items
        $scanner = Find-Scanner
        if (!$Offline) {
            Add-Type -AssemblyName System.Net.Http
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $options = New-Object Net.Http.HttpClientHandler
            $options.AllowAutoRedirect = $false
            $options.UseCookies = $false
            $options.UseDefaultCredentials = $false
            $http = New-Object Net.Http.HttpClient($options)
            $http.Timeout = [TimeSpan]::FromMinutes(3)
        }
        $treeAttempted = $false
        $treeFailure = $null
        foreach ($item in $items) {
            $file = Get-Target $item
            $entry = [ordered]@{name=$item.name; kind=$item.kind; language=$item.language; path=$file; status='failed'}
            $staging = $null
            try {
                Write-Host ("Checking {0}" -f $item.name)
                if (!$item.sha256 -and !$item.git_blob_sha1) {
                    if (!$treeAttempted) {
                        $treeAttempted = $true
                        try { $speechTree = @(Read-SpeechTree $http ([bool]$Offline)) } catch { $treeFailure = $_.Exception.Message }
                    }
                    if ($treeFailure) { throw $treeFailure }
                    Resolve-TreeEntry $speechTree $item
                    $entry.metadata_url = $speechTreeUrl
                    $entry.expected_digest = if ($item.sha256) { $item.sha256 } else { $item.git_blob_sha1 }
                }
                Assert-SafeDirectory ([IO.Path]::GetDirectoryName($file))
                if ([IO.File]::Exists($file)) {
                    $result = Test-Asset $file $item $scanner
                } else {
                    if ($Offline) { throw 'Missing local file. Run without --offline to download it.' }
                    $stageDir = Join-Path $kitRoot 'model-staging'
                    Assert-SafeDirectory $stageDir
                    # Preserve the file extension for antivirus format recognition. Models never load from staging.
                    $staging = Join-Path $stageDir ([Guid]::NewGuid().ToString('N') + [IO.Path]::GetExtension($file))
                    Save-Download $http $item $staging
                    $result = Test-Asset $staging $item $scanner
                    [IO.File]::Move($staging,$file)
                }
                $entry.status='verified'; $entry.sha256=$result.sha256; $entry.bytes=$result.bytes
            } catch {
                $entry.reason = ($_.Exception.Message -replace '(?i)https?://\S+', '[download URI]')
                Write-Host ('  Could not verify: ' + $entry.reason)
            } finally {
                if ($staging -and [IO.File]::Exists($staging)) {
                    try { [IO.File]::Delete($staging) } catch { $entry.cleanup_warning = 'A rejected temporary file could not be removed from model-staging.' }
                }
            }
            $records.Add([pscustomobject]$entry)
        }
        $failed = @($records | Where-Object { $_.status -ne 'verified' })
        $report.status = if ($failed.Count) { 'incomplete' } else { 'verified' }
        if ($failed.Count) { Write-Host 'Some files could not be approved. Check model-test-results\model-file-checks.json. Existing files that failed verification must be moved aside before a fresh download.'; return 2 }
        Write-Host 'All 13 files matched their pinned identities and received clean Microsoft Defender verdicts.'
        return 0
    } catch {
        $report.status = 'failed'; $report.reason = $_.Exception.Message
        Write-Host ('File checks stopped: ' + $report.reason)
        return 1
    } finally {
        if ($http) { $http.Dispose() }
        if ($guard) {
            try {
                $report.files = $records.ToArray()
                $report.finished = [DateTime]::UtcNow.ToString('o')
                [IO.File]::WriteAllText($reportFile,($report | ConvertTo-Json -Depth 5),$utf8)
            } finally { $guard.Dispose() }
        }
    }
}
if ($MyInvocation.InvocationName -ne '.') { exit (Main) }
