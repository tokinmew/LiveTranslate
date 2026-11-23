param([Parameter(Mandatory=$true)][string]$SetupExe,
      [string]$PreviousSetupKit, [string]$PreviousPortable)

$ErrorActionPreference = 'Stop'
$installer = (Get-Item -LiteralPath $SetupExe).FullName
$fixtureParent = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\qa'))
$fixture = Join-Path $fixtureParent ('s-' + [Guid]::NewGuid().ToString('N').Substring(0,12))
$staging = Join-Path $fixture 'Unpacked setup'
$managed = Join-Path $fixture 'User Programs/LiveTranslate'
$menu = Join-Path $fixture 'User Start Menu/LiveTranslate'
$installed = Join-Path $managed 'app'
$ownsFixture = $false

# These two files match the ZIP release. The other two are native packaging support.
$expected = @{}
if ([bool]$PreviousSetupKit -ne [bool]$PreviousPortable) { throw 'Pass both previous release inputs to check a managed upgrade.' }

function Assert-Check([bool]$condition, [string]$message) {
    if (!$condition) { throw $message }
}

function Assert-PlainFixture([string]$dir) {
    if ([IO.File]::GetAttributes($dir) -band [IO.FileAttributes]::ReparsePoint) {
        throw "Unexpected link in test directory: $dir"
    }
    foreach ($child in [IO.Directory]::EnumerateFileSystemEntries($dir)) {
        $attributes = [IO.File]::GetAttributes($child)
        if ($attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Unexpected link: $child" }
        if ($attributes -band [IO.FileAttributes]::Directory) { Assert-PlainFixture $child }
    }
}

function Invoke-TestInstall {
    $result = $installMethod.Invoke($null, [string[]]@($staging, $managed, $menu))
    if (($result -is [int] -and $result -ne 0) -or ($result -is [bool] -and !$result)) {
        throw "Setup returned $result"
    }
}

try {
    Assert-Check (!(Test-Path -LiteralPath $fixture)) 'Fixture unexpectedly already exists.'
    [void][IO.Directory]::CreateDirectory($staging)
    $ownsFixture = $true
    $assembly = [Reflection.Assembly]::LoadFrom($installer)
    $pins = $assembly.GetType('LiveTranslate.Setup.GeneratedPins',$true)
    $expected['Setup.ps1'] = $pins.GetField('ScriptHash',[Reflection.BindingFlags]'Static,NonPublic').GetRawConstantValue()
    $expected['LiveTranslate.Launcher.exe'] = $pins.GetField('LauncherHash',[Reflection.BindingFlags]'Static,NonPublic').GetRawConstantValue()
    $expected['files.json'] = $pins.GetField('ManifestHash',[Reflection.BindingFlags]'Static,NonPublic').GetRawConstantValue()
    $expected['Portable.zip'] = $pins.GetField('PortableHash',[Reflection.BindingFlags]'Static,NonPublic').GetRawConstantValue()
    $payload = $assembly.GetType('LiveTranslate.Setup.SetupPayload', $true)
    $flags = [Reflection.BindingFlags]'Static,Public,NonPublic'
    $extractMethod = $payload.GetMethod('Extract', $flags)
    $installMethod = $payload.GetMethod('InstallFrom', $flags)
    Assert-Check ($null -ne $extractMethod -and $null -ne $installMethod) 'Setup entry points missing.'
    [void]$extractMethod.Invoke($null, [string[]]@($staging))
    $members = [IO.Directory]::GetFileSystemEntries($staging)
    Assert-Check ($members.Count -eq $expected.Count) 'Unexpected extracted setup members.'
    foreach ($member in $expected.Keys) {
        $actual = (Get-FileHash -LiteralPath (Join-Path $staging $member) -Algorithm SHA256).Hash
        Assert-Check ($actual -ieq $expected[$member]) "Payload hash mismatch: $member"
    }
    Write-Output 'PASS: Original portable ZIP and manifest match; desktop setup support matches embedded pins.'

    if ($PreviousSetupKit) {
        $old = Join-Path $fixture 'old'
        [void][IO.Directory]::CreateDirectory($old)
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $oldKit = [IO.Compression.ZipFile]::OpenRead((Get-Item -LiteralPath $PreviousSetupKit).FullName)
        try {
            foreach ($name in @('files.json','Setup.ps1')) {
                [IO.Compression.ZipFileExtensions]::ExtractToFile($oldKit.GetEntry($name),(Join-Path $old $name))
            }
        } finally { $oldKit.Dispose() }
        . (Join-Path $old 'Setup.ps1')
        Install-Portable (Get-Item -LiteralPath $PreviousPortable).FullName $managed $menu
        Assert-Check ([IO.File]::Exists((Join-Path $installed 'Start.cmd'))) 'Legacy release was not installed.'
        $saved = Join-Path $installed 'data/local-model-test.bin'
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($saved))
        [IO.File]::WriteAllText($saved, 'Keep this model')
        [IO.File]::WriteAllText((Join-Path $installed 'START-HERE.txt'), 'Modified previous release note')
        [void][IO.Directory]::CreateDirectory((Join-Path $installed 'docs'))
        [IO.File]::WriteAllText((Join-Path $installed 'docs/START-HERE.txt'), 'Personal note at destination')
        [IO.File]::WriteAllText((Join-Path $installed 'my-personal-notes.txt'), 'Untouched loose file')
    }
    Invoke-TestInstall
    . (Join-Path $staging 'Setup.ps1')
    $records = Read-List
    Assert-Check ($records.ContainsKey('scripts/Start.cmd') -and $records.ContainsKey('docs/START-HERE.txt')) 'Expected the organized release.'
    $rootFiles = @([IO.Directory]::GetFiles($installed) | ForEach-Object { [IO.Path]::GetFileName($_) })
    if ($PreviousSetupKit) {
        Assert-Check ($rootFiles.Count -eq 2 -and $rootFiles -ccontains 'LiveTranslate.exe') 'Unexpected upgrade root.'
        Assert-Check ([IO.File]::ReadAllText((Join-Path $installed 'my-personal-notes.txt')) -ceq 'Untouched loose file') 'The upgrade lost personal notes.'
        Assert-Check ([IO.File]::ReadAllText($saved) -ceq 'Keep this model') 'The version upgrade lost the extra model.'
        $backup = Join-Path $installed ('migration-backup/' + $releaseVersion.ToString(3))
        Assert-Check ([IO.File]::ReadAllText((Join-Path $backup 'previous-root/START-HERE.txt')) -ceq 'Modified previous release note') 'Lost modified legacy file.'
        Assert-Check ([IO.File]::ReadAllText((Join-Path $backup 'previous-destination/docs/START-HERE.txt')) -ceq 'Personal note at destination') 'Lost conflicting file.'
    } else {
        Assert-Check ($rootFiles.Count -eq 1 -and $rootFiles[0] -ceq 'LiveTranslate.exe') 'Unexpected loose root files.'
    }
    Assert-Check (Test-InstalledRelease $installed $records) 'Installed release failed its file checks.'
    $ver = [Diagnostics.FileVersionInfo]::GetVersionInfo((Join-Path $installed 'LiveTranslate.exe'))
    Assert-Check ($ver.FileVersion -eq ($releaseVersion.ToString(3) + '.0')) "Unexpected installed application version $($ver.FileVersion)."
    $shortcut = Join-Path $menu 'LiveTranslate.lnk'
    Assert-Check ([IO.File]::Exists($shortcut)) 'Missing application shortcut.'
    Assert-Check ([IO.File]::Exists((Join-Path $menu 'Uninstall LiveTranslate.lnk'))) 'Missing uninstall shortcut.'
    $shell = New-Object -ComObject WScript.Shell
    try {
        $link = $shell.CreateShortcut($shortcut)
        try {
            Assert-Check ($link.TargetPath -ieq (Join-Path $installed 'LiveTranslate.exe')) 'Incorrect first-run shortcut target.'
            Assert-Check (!$link.Arguments) 'Unexpected first-run shortcut arguments.'
        } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($link) }
    } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell) }
    Write-Output ("PASS: Verified {0} installed files, version {1}, the organized root and application shortcut." -f $records.Count,$ver.FileVersion)

    $sentinel = Join-Path $installed 'retained-user-file.txt'
    [IO.File]::WriteAllText($sentinel, 'Preserve user content')
    [IO.File]::WriteAllText((Join-Path $installed 'docs/START-HERE.txt'), 'Simulated interrupted installation')
    Invoke-TestInstall
    Assert-Check (Test-InstalledRelease $installed $records) 'Repair did not restore the verified release.'
    Assert-Check ([IO.File]::ReadAllText($sentinel) -ceq 'Preserve user content') 'Repair lost user content.'
    Write-Output 'PASS: Same-version repair restored damaged content and retained the extra user file.'

    Uninstall-Portable $managed $menu $false
    Assert-Check ([IO.File]::Exists($sentinel) -and ![IO.File]::Exists((Join-Path $installed 'LiveTranslate.exe'))) 'Uninstall with retention did not preserve the user file or remove the dashboard.'
    Assert-Check (![IO.Directory]::Exists((Join-Path $installed '.lt-setup')) -and ![IO.Directory]::Exists($menu)) 'Retained uninstall left known support or shortcuts.'
    Invoke-TestInstall
    Assert-Check (Test-InstalledRelease $installed $records) 'Reinstallation after retaining data failed.'
    Assert-Check ([IO.File]::Exists($sentinel)) 'Reinstallation lost the retained user file.'
    Uninstall-Portable $managed $menu $true
    Assert-Check (![IO.Directory]::Exists($installed) -and ![IO.Directory]::Exists($menu)) 'Uninstall left application files or shortcuts.'
    Write-Output 'PASS: Uninstall removed the isolated application and shortcuts.'
} finally {
    if ($ownsFixture -and [IO.Directory]::Exists($fixture)) {
        $target = [IO.Path]::GetFullPath($fixture)
        if ([IO.Path]::GetDirectoryName($target) -ine $fixtureParent -or
            [IO.Path]::GetFileName($target) -notmatch '^s-[a-f0-9]{12}$') {
            throw 'Refusing to clean up an unexpected test location.'
        }
        Assert-PlainFixture $target
        [IO.Directory]::Delete($target, $true)
    }
}
