param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$releaseVersion = [version]'__VERSION__'
$packagePin = '__ARCHIVE_SHA256__'
$listPin = '__MANIFEST_SHA256__'
$launcherPin = '__LAUNCHER_SHA256__'
$setupFile = $PSCommandPath
$listFile = Join-Path $PSScriptRoot 'files.json'
$brand = 'LiveTranslate Windows per-user install v1'
$legacyRoot = @{
# __LEGACY_ROOT_HASHES__
}

function Hash-Stream($stream) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Plain-Path([string]$path) {
    $current = [IO.Path]::GetFullPath($path)
    while ($current) {
        $item = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
        if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "A linked path is unsupported: $current" }
        $current = [IO.Path]::GetDirectoryName($current)
    }
}

function Under([string]$parent,[string]$name) {
    if ([IO.Path]::IsPathRooted($name) -or $name.Contains(':') -or $name -match '(^|[/\\])\.\.([/\\]|$)') { throw 'Invalid package path.' }
    $absolute = [IO.Path]::GetFullPath([IO.Path]::Combine($parent,$name))
    if (!$absolute.StartsWith($parent.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid package path.' }
    $absolute
}

function Read-List {
    if ((Get-FileHash -LiteralPath $listFile -Algorithm SHA256).Hash -ine $listPin) { throw 'The setup file list changed. Extract a fresh copy of the setup ZIP.' }
    $items = @{}
    foreach ($row in ([IO.File]::ReadAllText($listFile) | ConvertFrom-Json)) {
        $items.Add([string]$row[0],$row)
    }
    $items
}

function Stage-File($stream,[string]$stage,$record) {
    $output = Under $stage $record[0]
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($output))
    $out = [IO.File]::Open($output,'CreateNew','Write','None')
    try { $stream.CopyTo($out) } finally { $out.Dispose() }
    if (([IO.FileInfo]$output).Length -ne [long]$record[1] -or (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash -ine $record[2]) {
        throw "The selected release file failed verification: $($record[0])"
    }
}

function Stage-Portable([string]$selected,[string]$stage,$records) {
    $selected = [IO.Path]::GetFullPath($selected)
    Plain-Path $selected
    if ([IO.Path]::GetExtension($selected) -ieq '.zip') {
        Add-Type -AssemblyName System.IO.Compression
        $file = [IO.File]::OpenRead($selected)
        try {
            if ((Hash-Stream $file) -ine $packagePin) { throw 'The selected ZIP does not match this setup release.' }
            $file.Position = 0
            $zip = [IO.Compression.ZipArchive]::new($file,[IO.Compression.ZipArchiveMode]::Read,$true)
            try {
                if ($zip.Entries.Count -ne $records.Count) { throw 'The package content list changed.' }
                foreach ($entry in $zip.Entries) {
                    if (!$entry.FullName.StartsWith('LiveTranslate/')) { throw 'Unexpected ZIP member.' }
                    $record = $records[$entry.FullName.Substring(14)]
                    if (!$record -or $entry.Length -ne $record[1]) { throw 'Unexpected ZIP member.' }
                    $inputStream = $entry.Open()
                    try { Stage-File $inputStream $stage $record } finally { $inputStream.Dispose() }
                }
            } finally { $zip.Dispose() }
        } finally { $file.Dispose() }
    } else {
        if ([IO.File]::Exists($selected) -and [IO.Path]::GetFileName($selected) -iin @('Start.cmd','LiveTranslate.exe')) { $selected = [IO.Path]::GetDirectoryName($selected) }
        if (![IO.Directory]::Exists($selected)) { throw 'Select the full Windows ZIP or its extracted LiveTranslate.exe.' }
        foreach ($record in $records.Values) {
            $path = Under $selected $record[0]
            Plain-Path $path
            $source = [IO.File]::OpenRead($path)
            try { Stage-File $source $stage $record } finally { $source.Dispose() }
        }
    }
}

function Walk-Files([string]$dir) {
    foreach ($path in [IO.Directory]::EnumerateFileSystemEntries($dir)) {
        $attributes = [IO.File]::GetAttributes($path)
        if ($attributes -band [IO.FileAttributes]::ReparsePoint) { throw "A linked item requires attention: $path" }
        if ($attributes -band [IO.FileAttributes]::Directory) { Walk-Files $path }
        else { $path }
    }
}

function Remove-ManagedTree([string]$base,[string]$name) {
    if ($name -notin @('stage','previous','app')) { throw 'Unexpected managed directory.' }
    $target = Under $base $name
    if (![IO.Directory]::Exists($target)) { return }
    Plain-Path $target
    Walk-Files $target | Out-Null
    [IO.Directory]::Delete($target,$true)
}

function Check-Idle([string]$appDir) {
    foreach ($name in @('.livetranslate-update/transaction.json')) {
        if ([IO.File]::Exists((Under $appDir $name))) { throw 'Open LiveTranslate to finish its pending update, then close it and retry.' }
    }
    foreach ($name in @('.livetranslate-update/run.lock','.livetranslate-update/install.lock','setup.lock','setup-cache/setup.lock',
                        'model-test-results/offline-setup.lock','model-test-results/model-fetch.lock',
                        'data/.model-test.lock','model-staging/quality/setup.lock')) {
        $lock = Under $appDir $name
        Plain-Path $lock
        if ([IO.File]::Exists($lock)) {
            try {
                $probe = [IO.File]::Open($lock,'Open','ReadWrite','None')
                try {
                    if ($probe.Length -gt 0) { $probe.Lock(0,1); $probe.Unlock(0,1) }
                } finally { $probe.Dispose() }
            } catch { throw 'Close LiveTranslate and any model installation or update, then try again.' }
        }
    }
}

function Setup-Links([string]$menu,[string]$appDir,[bool]$remove,[bool]$checkOnly=$false) {
    if ($launcherPin) { Set-DesktopLinks $menu $appDir $remove $checkOnly; return }
    Plain-Path $menu
    if (![IO.Directory]::Exists($menu)) {
        if ($remove -or $checkOnly) { return }
        [void][IO.Directory]::CreateDirectory($menu)
    }
    $shell = New-Object -ComObject WScript.Shell
    $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    try {
        foreach ($title in @('LiveTranslate','Uninstall LiveTranslate')) {
            $linkFile = Under $menu ($title+'.lnk')
            Plain-Path $linkFile
            if ($title -eq 'LiveTranslate') { $target = Under $appDir 'LiveTranslate.exe'; $arguments = '' }
            else { $target = $ps; $arguments = '-NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "'+(Under $appDir '.lt-setup/Setup.ps1')+'" -Uninstall' }
            if (($remove -or $checkOnly) -and ![IO.File]::Exists($linkFile)) { continue }
            $link = $shell.CreateShortcut($linkFile)
            try {
                if ([IO.File]::Exists($linkFile) -and ($link.TargetPath -ine $target -or $link.Arguments -ine $arguments)) {
                    if ($remove) { continue }
                    throw "A different shortcut exists at $linkFile"
                }
                if ($checkOnly) { continue }
                if ($remove) { [IO.File]::Delete($linkFile) }
                else {
                    $link.TargetPath = $target
                    if ($arguments) { $link.Arguments = $arguments }
                    # Windows keeps a process's working directory in use. The
                    # uninstaller can erase appDir only when it starts outside it.
                    $link.WorkingDirectory = if ($title -eq 'LiveTranslate') { $appDir } else { [IO.Path]::GetDirectoryName($appDir) }
                    $link.IconLocation = (Under $appDir 'LiveTranslate.exe')+',0'
                    $link.Save()
                }
            } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($link) }
        }
    } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell) }
    if ($remove -and @([IO.Directory]::GetFileSystemEntries($menu)).Length -eq 0) { [IO.Directory]::Delete($menu) }
}

function Test-InstalledRelease([string]$appDir,$records) {
    foreach ($name in $legacyRoot.Keys) { if ([IO.File]::Exists((Under $appDir $name))) { return $false } }
    foreach ($record in $records.Values) {
        $path = Under $appDir $record[0]
        Plain-Path $path
        if (![IO.File]::Exists($path) -or ([IO.FileInfo]$path).Length -ne [long]$record[1] -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ine $record[2]) { return $false }
    }
    $supportFiles = @(@('.lt-setup/files.json',$listPin),@('.lt-setup/Setup.ps1',(Get-FileHash -LiteralPath $setupFile -Algorithm SHA256).Hash))
    if ($launcherPin) { $supportFiles += ,@('.lt-setup/LiveTranslate.Launcher.exe',$launcherPin) }
    foreach ($pair in $supportFiles) {
        $path = Under $appDir $pair[0]
        Plain-Path $path
        if (![IO.File]::Exists($path) -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ine $pair[1]) { return $false }
    }
    return $true
}

function Open-Managed([string]$base,[bool]$freshAllowed) {
    Plain-Path $base
    $marker = Under $base '.managed'
    Plain-Path $marker
    if (![IO.File]::Exists($marker)) {
        if (!$freshAllowed -or ([IO.Directory]::Exists($base) -and @([IO.Directory]::EnumerateFileSystemEntries($base)).Length)) {
            throw "This directory already contains an unmanaged installation: $base"
        }
        [void][IO.Directory]::CreateDirectory($base)
        [IO.File]::WriteAllText($marker,$brand)
    }
    if ([IO.File]::ReadAllText($marker) -cne $brand) { throw 'Unexpected installation marker.' }
    $lock = Under $base 'setup.lock'
    Plain-Path $lock
    [IO.File]::Open($lock,'OpenOrCreate','ReadWrite','None')
}

function Move-StagedDirectory([string]$source,[string]$destination) {
    for ($attempt = 0; ; $attempt++) {
        try { [IO.Directory]::Move($source,$destination); return }
        catch {
            $code = $_.Exception.GetBaseException().HResult -band 65535
            if ($attempt -ge 8 -or $code -notin @(5,32,33) -or ![IO.Directory]::Exists($source) -or [IO.Directory]::Exists($destination)) { throw }
            Start-Sleep -Milliseconds (100 * ($attempt + 1))
        }
    }
}

# __DESKTOP_INTEGRATION__

function Save-LayoutConflict([string]$file,[string]$stage,[string]$relative) {
    $backup = Under $stage ('migration-backup/' + $releaseVersion.ToString(3) + '/' + $relative)
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($backup))
    $path = $backup
    $number = 0
    while ([IO.File]::Exists($path) -or [IO.Directory]::Exists($path)) {
        if ([IO.File]::Exists($path) -and (Get-FileHash -LiteralPath $path).Hash -eq (Get-FileHash -LiteralPath $file).Hash) { return }
        $number++
        $path = $backup + '.' + $number
    }
    [IO.File]::Copy($file,$path)
}

function Test-StockFeed([string]$appDir,$records) {
    $entries = @($records.Values | Where-Object { ([string]$_[0]).StartsWith('updates/feed/',[StringComparison]::OrdinalIgnoreCase) })
    if ($entries.Count -ne 2) { return $false }
    foreach ($record in $entries) {
        $file = Under $appDir $record[0]
        Plain-Path $file
        if (![IO.File]::Exists($file) -or ([IO.FileInfo]$file).Length -ne [long]$record[1] -or
                (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine $record[2]) { return $false }
    }
    return $true
}

function Copy-RetainedFiles([string]$appDir,[string]$stage,$records,$actual) {
    $oldList = Under $appDir '.lt-setup/files.json'
    $oldNames = @{}
    # The current kit already identifies every owned file for a
    # same-version repair, even if its installed file list broke.
    if ([IO.File]::Exists($oldList)) {
        try {
            foreach ($row in ([IO.File]::ReadAllText($oldList) | ConvertFrom-Json)) { $oldNames[[string]$row[0]] = $row }
        } catch { $oldNames = @{} }
    }
    $preserve = @{}
    $ownedFeed = (Test-StockFeed $appDir $records) -or (Test-StockFeed $appDir $oldNames)
    foreach ($file in (Walk-Files $appDir)) {
        $name = $file.Substring($appDir.Length+1).Replace('\','/')
        $customFeedFile = (!$ownedFeed -and $name.StartsWith('updates/feed/',[StringComparison]::OrdinalIgnoreCase))
        if ($customFeedFile -and $records.ContainsKey($name)) {
            $preserve['previous-feed/' + $name.Substring(13)] = $file
            continue
        }
        if ($legacyRoot.ContainsKey($name)) {
            if ((Get-FileHash -LiteralPath $file).Hash -ine $legacyRoot[$name]) { $preserve['previous-root/' + $name] = $file }
            continue
        }
        if ($records.ContainsKey($name)) {
            $leaf = [IO.Path]::GetFileName($name)
            if ($oldNames.ContainsKey('Start.cmd') -and !$oldNames.ContainsKey($name) -and
                    $legacyRoot.ContainsKey($leaf) -and (Get-FileHash -LiteralPath $file).Hash -ine $records[$name][2]) {
                $preserve['previous-destination/' + $name] = $file
            }
            continue
        }
        if ($name.StartsWith('.lt-setup/') -or (!$customFeedFile -and $actual -ne $releaseVersion -and $oldNames.ContainsKey($name))) { continue }
        if ($name.StartsWith('.livetranslate-update/')) { continue }
        if ($name -eq 'setup.lock' -and !([IO.FileInfo]$file).Length) { continue }
        $copy = Under $stage $name
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($copy))
        [IO.File]::Copy($file,$copy)
    }
    foreach ($name in $preserve.Keys) { Save-LayoutConflict $preserve[$name] $stage $name }
}

function Install-Portable([string]$source,[string]$base,[string]$menu) {
    $records = Read-List
    $guard = Open-Managed $base $true
    try {
        $appDir = Under $base 'app'; $stage = Under $base 'stage'; $previous = Under $base 'previous'
        $actual = $null
        foreach ($p in @($appDir,$stage,$previous)) { Plain-Path $p }
        if ([IO.Directory]::Exists($previous) -and ![IO.Directory]::Exists($appDir)) { Move-StagedDirectory $previous $appDir }
        Setup-Links $menu $appDir $false $true
        if ([IO.Directory]::Exists($appDir)) {
            Check-Idle $appDir
            $exe = Under $appDir 'LiveTranslate.exe'
            if ([IO.File]::Exists($exe)) {
                $ver = [Diagnostics.FileVersionInfo]::GetVersionInfo($exe)
                $actual = [version]::new($ver.FileMajorPart,$ver.FileMinorPart,$ver.FileBuildPart)
                if ($actual -gt $releaseVersion -or ($actual -eq $releaseVersion -and (Test-InstalledRelease $appDir $records))) {
                    Setup-Links $menu $appDir $false
                    Remove-ManagedTree $base 'previous'
                    Remove-ManagedTree $base 'stage'
                    return "LiveTranslate $actual is already installed. Your Start menu shortcuts are ready."
                }
            }
        }
        Remove-ManagedTree $base 'previous'
        Remove-ManagedTree $base 'stage'
        [void][IO.Directory]::CreateDirectory($stage)
        try {
            Stage-Portable $source $stage $records
            if ([IO.Directory]::Exists($appDir)) {
                Copy-RetainedFiles $appDir $stage $records $actual
                Check-Idle $appDir
            }
            $support = Under $stage '.lt-setup'
            [void][IO.Directory]::CreateDirectory($support)
            [IO.File]::Copy($setupFile,(Under $support 'Setup.ps1'))
            [IO.File]::Copy($listFile,(Under $support 'files.json'))
            if ($launcherPin) {
                $launcher = Join-Path $PSScriptRoot 'LiveTranslate.Launcher.exe'
                if ((Get-FileHash -LiteralPath $launcher).Hash -ine $launcherPin) { throw 'The desktop launcher changed.' }
                [IO.File]::Copy($launcher,(Under $support 'LiveTranslate.Launcher.exe'))
            }
            if ([IO.Directory]::Exists($appDir)) { Move-StagedDirectory $appDir $previous }
            try { Move-StagedDirectory $stage $appDir }
            catch { if ([IO.Directory]::Exists($previous)) { Move-StagedDirectory $previous $appDir }; throw }
        } finally { Remove-ManagedTree $base 'stage' }
        Setup-Links $menu $appDir $false
        Remove-ManagedTree $base 'previous'
        return 'LiveTranslate is installed. Open LiveTranslate from the Start menu when ready.'
    } finally { $guard.Dispose() }
}

function Remove-PackagedFiles([string]$appDir,$records) {
    $stockFeed = Test-StockFeed $appDir $records
    foreach ($record in $records.Values) {
        if (!$stockFeed -and ([string]$record[0]).StartsWith('updates/feed/',[StringComparison]::OrdinalIgnoreCase)) { continue }
        $file = Under $appDir $record[0]
        Plain-Path $file
        if ([IO.File]::Exists($file)) { [IO.File]::Delete($file) }
    }
    if ($stockFeed) {
        foreach ($name in @('updates/feed','updates')) {
            $folder = Under $appDir $name
            if ([IO.Directory]::Exists($folder) -and ![IO.Directory]::GetFileSystemEntries($folder).Length) { [IO.Directory]::Delete($folder) }
        }
    }
}

function Uninstall-Portable([string]$base,[string]$menu,[bool]$erase) {
    $records = Read-List
    $guard = Open-Managed $base $false
    try {
        $appDir = Under $base 'app'
        Plain-Path $appDir
        Check-Idle $appDir
        if ([IO.Directory]::Exists((Under $base 'previous'))) { throw 'Open the setup kit to finish recovering the prior installation first.' }
        if ($erase) { Remove-ManagedTree $base 'app' }
        else {
            Remove-PackagedFiles $appDir $records
        }
        Setup-Links $menu $appDir $true
        if (!$erase) {
            $support = Under $appDir '.lt-setup'
            Plain-Path $support
            foreach ($name in @('files.json','LiveTranslate.Launcher.exe','Setup.ps1')) {
                $file = Under $support $name
                Plain-Path $file
                if ([IO.File]::Exists($file)) { [IO.File]::Delete($file) }
            }
            if ([IO.Directory]::Exists($support) -and ![IO.Directory]::GetFileSystemEntries($support).Length) { [IO.Directory]::Delete($support) }
        }
    } finally { $guard.Dispose() }
}

if ($MyInvocation.InvocationName -eq '.') { return }
Add-Type -AssemblyName System.Windows.Forms
$base = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\LiveTranslate'
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'LiveTranslate'
try {
    if ($Uninstall) {
        $answer = [Windows.Forms.MessageBox]::Show("Remove LiveTranslate from this Windows profile?`n`nYes = also erase all models and other files inside $base\app.`nNo = remove the packaged application and keep extra files, including models.`nCancel = leave it installed.",'Uninstall LiveTranslate','YesNoCancel','Question','Button3')
        if ($answer -eq 'Cancel') { return }
        Set-Location -LiteralPath $env:SystemRoot
        [Environment]::CurrentDirectory = $env:SystemRoot
        Uninstall-Portable $base $menu ($answer -eq 'Yes')
        $message = 'LiveTranslate has been removed from the Start menu.'
    } else {
        $file = Join-Path $PSScriptRoot ("LiveTranslate-" + $releaseVersion.ToString(3) + "-Windows-Test.zip")
        if (![IO.File]::Exists($file)) {
            $picker = New-Object Windows.Forms.OpenFileDialog
            $picker.Title = 'Choose the full LiveTranslate Windows ZIP or its extracted LiveTranslate.exe'
            $picker.Filter = 'LiveTranslate portable ZIP or application|*.zip;LiveTranslate.exe'
            try { if ($picker.ShowDialog() -ne 'OK') { return }; $file = $picker.FileName } finally { $picker.Dispose() }
        }
        $message = Install-Portable $file $base $menu
    }
    [void][Windows.Forms.MessageBox]::Show($message,'LiveTranslate setup')
} catch {
    [void][Windows.Forms.MessageBox]::Show($_.Exception.Message,'LiveTranslate setup','OK','Error')
    exit 1
}
