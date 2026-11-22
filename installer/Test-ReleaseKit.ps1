param([Parameter(Mandatory=$true)][string]$Kit,[Parameter(Mandatory=$true)][string]$Portable)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = (Get-Item -LiteralPath $Portable).FullName
$kitZip = (Get-Item -LiteralPath $Kit).FullName
$temp = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ('release-test-'+[Guid]::NewGuid().ToString('N'))))
try {
    $testKit = Join-Path $temp 'kit'
    [IO.Directory]::CreateDirectory($testKit) | Out-Null
    [IO.Compression.ZipFile]::ExtractToDirectory($kitZip,$testKit)
    . (Join-Path $testKit 'Setup.ps1')
    $managed = Join-Path $temp 'Programs/LiveTranslate'
    $menu = Join-Path $temp 'Shortcuts/LiveTranslate'
    Install-Portable $zip $managed $menu
    $installed = Under $managed 'app'
    $exe = Under $installed 'LiveTranslate.exe'
    $ver = [Diagnostics.FileVersionInfo]::GetVersionInfo($exe)
    if ([version]::new($ver.FileMajorPart,$ver.FileMinorPart,$ver.FileBuildPart) -ne $releaseVersion) { throw 'Incorrect dashboard version' }
    if (![IO.File]::Exists((Under $menu 'LiveTranslate.lnk'))) { throw 'Missing launch shortcut' }
    Uninstall-Portable $managed $menu $true
    if ([IO.Directory]::Exists($installed) -or [IO.Directory]::Exists($menu)) { throw 'Test uninstall incomplete' }
    Write-Output ("Verified Windows release {0}, {1} portable files, shortcut creation and uninstall." -f $releaseVersion,(Read-List).Count)
} finally {
    if ([IO.Directory]::Exists($temp) -and [IO.Path]::GetDirectoryName($temp) -eq $PSScriptRoot -and
        [IO.Path]::GetFileName($temp) -match '^release-test-[a-f0-9]{32}$') { [IO.Directory]::Delete($temp,$true) }
}
