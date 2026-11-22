param([Parameter(Mandatory=$true)][string]$Python)
$ErrorActionPreference = 'Stop'
$pythonExe = (Get-Item -LiteralPath $Python).FullName
$builder = Join-Path $PSScriptRoot 'build_kit.py'
$tmp = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ('fixture-'+[Guid]::NewGuid().ToString('N'))))
$program = Join-Path $tmp 'Program Files [test]'
$menuFixture = Join-Path $tmp 'Start Menu [test]'
$root = Join-Path $program 'LiveTranslate'
$menu = Join-Path $menuFixture 'LiveTranslate'
$app = Join-Path $root 'app'
$csc = Join-Path $env:SystemRoot 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
Add-Type -AssemblyName System.IO.Compression.FileSystem
function Check([bool]$value,[string]$description) {
    if (!$value) { throw "FAIL $description" }
    Write-Output "PASS $description"
}
function Expect-Failure([scriptblock]$action,[string]$phrase) {
    try { & $action | Out-Null } catch {
        if ($_.Exception.Message.Contains($phrase)) { Write-Output "PASS $phrase"; return }
        throw
    }
    throw "Expected failure: $phrase"
}
try {
    foreach ($ver in @('0.6.5','0.6.6')) {
        $dir = Join-Path $tmp $ver
        $tree = Join-Path $dir 'source/LiveTranslate'
        [void][IO.Directory]::CreateDirectory((Join-Path $tree 'backend'))
        $src = Join-Path $dir 'App.cs'
        [IO.File]::WriteAllText($src,('[assembly:System.Reflection.AssemblyFileVersion("'+$ver+'.0")]class Dummy { static void Main() {} }'))
        & $csc /nologo /target:winexe ("/out:"+ (Join-Path $tree 'LiveTranslate.exe')) $src
        if ($LASTEXITCODE) { throw 'Fixture build failed.' }
        [IO.File]::WriteAllText((Join-Path $tree 'backend/worker.py'),$ver)
        [IO.File]::WriteAllText((Join-Path $tree 'Start.cmd'),'exit /b 0')
        $zip = Join-Path $dir 'test.zip'
        & $pythonExe -I -B -c "from pathlib import Path; import sys,zipfile; root=Path(sys.argv[1]); z=zipfile.ZipFile(sys.argv[2],'x'); [z.write(p,p.relative_to(root).as_posix()) for p in root.rglob('*') if p.is_file()]; z.close()" (Join-Path $dir 'source') $zip
        if ($LASTEXITCODE) { throw 'Fixture ZIP failed.' }
        $kit = Join-Path $dir 'setup.zip'
        & $pythonExe -I -B $builder --portable $zip --output $kit --version $ver
        if ($LASTEXITCODE) { throw 'Setup build failed.' }
        [IO.Compression.ZipFile]::ExtractToDirectory($kit,(Join-Path $dir 'kit'))
    }
    $old = Join-Path $tmp '0.6.5'
    $new = Join-Path $tmp '0.6.6'
    . (Join-Path $old 'kit/Setup.ps1')
    Install-Portable (Join-Path $old 'source/LiveTranslate/Start.cmd') $root $menu
    Check ([IO.File]::Exists((Join-Path $app 'Start.cmd'))) 'Install verified extracted tree'
    Check ([IO.File]::Exists((Join-Path $menu 'Uninstall LiveTranslate.lnk'))) 'Uninstall shortcut'
    [void][IO.Directory]::CreateDirectory((Join-Path $app 'data'))
    $model = Join-Path $app 'data/my-model.bin'
    [IO.File]::WriteAllText($model,'MODEL')
    $prefs = Join-Path $app 'preferences.json'
    [IO.File]::WriteAllText($prefs,'KEEP')
    . (Join-Path $new 'kit/Setup.ps1')
    Expect-Failure { Install-Portable (Join-Path $old 'test.zip') $root $menu } 'does not match'
    $wrong = Join-Path $old 'source/LiveTranslate/Start.cmd'
    Expect-Failure { Install-Portable $wrong $root $menu } 'failed verification'
    Check ([IO.File]::ReadAllText((Join-Path $app 'backend/worker.py')) -eq '0.6.5') 'Old app intact after failed validation'
    $state = Join-Path $app '.livetranslate-update'
    [void][IO.Directory]::CreateDirectory($state)
    $journal = Join-Path $state 'transaction.json'
    [IO.File]::WriteAllText($journal,'{}')
    Expect-Failure { Install-Portable (Join-Path $new 'test.zip') $root $menu } 'pending update'
    [IO.File]::Delete($journal)
    foreach ($name in @('.livetranslate-update/run.lock','setup.lock','model-test-results/model-fetch.lock','data/.model-test.lock')) {
        $path = Join-Path $app $name
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path))
        $held = [IO.File]::Open($path,'OpenOrCreate','ReadWrite','Read')
        try { Expect-Failure { Uninstall-Portable $root $menu $true } 'Close LiveTranslate' } finally { $held.Dispose() }
        Check ([IO.File]::Exists((Join-Path $app 'Start.cmd'))) "Active $name leaves the installation intact"
    }
    $shortcut = Join-Path $menu 'Uninstall LiveTranslate.lnk'
    $shortcutBackup = [IO.File]::ReadAllBytes($shortcut)
    $com = New-Object -ComObject WScript.Shell
    try {
        $other = $com.CreateShortcut($shortcut)
        try { $other.TargetPath = $csc; $other.Save() } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($other) }
    } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($com) }
    $unrelated = [IO.File]::ReadAllBytes($shortcut)
    Expect-Failure { Install-Portable (Join-Path $new 'test.zip') $root $menu } 'different shortcut'
    Check ([IO.File]::ReadAllText((Join-Path $app 'backend/worker.py')) -eq '0.6.5') 'Shortcut conflict leaves installed version intact'
    [IO.File]::WriteAllBytes($shortcut,$shortcutBackup)
    Install-Portable (Join-Path $new 'test.zip') $root $menu
    Check ([IO.File]::ReadAllText((Join-Path $app 'backend/worker.py')) -eq '0.6.6') 'New version installed'
    Check (([IO.File]::ReadAllText($model) -eq 'MODEL') -and ([IO.File]::ReadAllText($prefs) -eq 'KEEP')) 'Model and settings preserved during upgrade'
    Install-Portable (Join-Path $new 'test.zip') $root $menu
    [IO.File]::Delete((Join-Path $app 'Start.cmd'))
    [IO.File]::WriteAllText((Join-Path $app 'backend/worker.py'),'WRONG')
    [IO.File]::WriteAllText((Join-Path $app '.lt-setup/files.json'),'{')
    Install-Portable (Join-Path $new 'test.zip') $root $menu
    Check ((Test-InstalledRelease $app (Read-List)) -and [IO.File]::ReadAllText($prefs) -eq 'KEEP' -and [IO.File]::ReadAllText($model) -eq 'MODEL') 'Same-version repair restores files and keeps model and settings'
    Uninstall-Portable $root $menu $false
    Check ((![IO.File]::Exists((Join-Path $app 'LiveTranslate.exe'))) -and [IO.File]::Exists($model) -and [IO.File]::Exists($prefs)) 'Uninstall with retention'
    Check (![IO.File]::Exists((Join-Path $menu 'LiveTranslate.lnk'))) 'Start menu cleanup'
    Install-Portable (Join-Path $new 'test.zip') $root $menu
    Check ([IO.File]::ReadAllText($model) -eq 'MODEL') 'Reinstall reuses retained files'
    . (Join-Path $old 'kit/Setup.ps1')
    Install-Portable (Join-Path $old 'test.zip') $root $menu
    Check ([IO.File]::ReadAllText((Join-Path $app 'backend/worker.py')) -eq '0.6.6') 'Older setup cannot downgrade'
    . (Join-Path $new 'kit/Setup.ps1')
    [IO.File]::WriteAllBytes($shortcut,$unrelated)
    Uninstall-Portable $root $menu $true
    Check (![IO.Directory]::Exists($app)) 'Explicit erase removes managed application'
    Check ([Convert]::ToBase64String([IO.File]::ReadAllBytes($shortcut)) -eq [Convert]::ToBase64String($unrelated)) 'Uninstall keeps unrelated user shortcut'
    Expect-Failure { Uninstall-Portable $tmp $menu $true } 'unmanaged'
    Expect-Failure { Under $root '../escape' } 'Invalid package path'
} finally {
    # Only the generated fixture inside this QA directory is cleaned.
    if ([IO.Directory]::Exists($tmp) -and [IO.Path]::GetDirectoryName($tmp) -eq $PSScriptRoot -and
        [IO.Path]::GetFileName($tmp) -match '^fixture-[a-f0-9]{32}$') { [IO.Directory]::Delete($tmp,$true) }
}
