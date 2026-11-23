param(
    [Parameter(Mandatory=$true)][string]$Portable,
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][string]$Icon,
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$Python
)
$ErrorActionPreference = 'Stop'
$archive = (Get-Item -LiteralPath $Portable).FullName
$iconPath = (Get-Item -LiteralPath $Icon).FullName
$target = [IO.Path]::GetFullPath($Output)
$versionParts = [version]$Version
if ($versionParts.ToString(3) -cne $Version -or $versionParts.Major -gt 65534 -or
    $versionParts.Minor -gt 65534 -or $versionParts.Build -gt 65534) { throw 'Expected a valid three-part release version.' }
if ([IO.File]::Exists($target)) { throw "Output already exists: $target" }
$compiler = Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$pythonExe = (Get-Item -LiteralPath $Python).FullName
$build = Join-Path $PSScriptRoot ('build-' + [Guid]::NewGuid().ToString('N'))
$launcher = Join-Path $build 'LiveTranslate.Launcher.exe'
$engine = Join-Path $build 'Setup.ps1'
$list = Join-Path $build 'files.json'
$pins = Join-Path $build 'GeneratedPins.cs'
$metadata = Join-Path $build 'Version.cs'
$manifest = Join-Path $build 'desktop.manifest'
$dashboard = Join-Path $build 'dashboard.exe'
$compiled = Join-Path $build 'Setup.exe'
[void][IO.Directory]::CreateDirectory($build)
try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try {
        $exe = $zip.GetEntry('LiveTranslate/LiveTranslate.exe')
        if (!$exe) { throw 'The portable ZIP has no root application.' }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($exe,$dashboard)
    } finally { $zip.Dispose() }
    if ([Diagnostics.FileVersionInfo]::GetVersionInfo($dashboard).FileVersion -ne "$Version.0") {
        throw 'The portable application version differs from the installer version.'
    }
    $attributes = "[assembly: System.Reflection.AssemblyVersion(`"$Version.0`")]`n[assembly: System.Reflection.AssemblyFileVersion(`"$Version.0`")]`n[assembly: System.Reflection.AssemblyInformationalVersion(`"$Version`")]"
    [IO.File]::WriteAllText($metadata,$attributes)
    $template = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'desktop.manifest'))
    [IO.File]::WriteAllText($manifest,$template.Replace('__VERSION__',"$Version.0"))
    $common = @('/nologo','/target:winexe','/platform:x64','/optimize+','/codepage:65001',
        '/r:System.Windows.Forms.dll','/r:System.Drawing.dll',"/win32icon:$iconPath","/win32manifest:$manifest")
    & $compiler @common "/out:$launcher" $metadata (Join-Path $PSScriptRoot 'InstalledLauncher.cs')
    if ($LASTEXITCODE) { throw 'Installation helper compilation failed.' }
    & $pythonExe -I -B (Join-Path $PSScriptRoot 'render_engine.py') $archive $launcher $build $Version
    if ($LASTEXITCODE) { throw 'Could not render the packaged installation engine.' }
    & $compiler @common "/resource:$archive,Portable.zip" "/resource:$list,files.json" "/resource:$engine,Setup.ps1" "/resource:$launcher,LiveTranslate.Launcher.exe" "/out:$compiled" $metadata $pins (Join-Path $PSScriptRoot 'SetupPayload.cs') (Join-Path $PSScriptRoot 'SetupWindow.cs')
    if ($LASTEXITCODE) { throw 'Desktop installer compilation failed.' }
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
    [IO.File]::Move($compiled,$target)
} finally {
    foreach ($file in @($dashboard,$manifest,$metadata,$pins,$list,$engine,$launcher,$compiled)) {
        if ([IO.File]::Exists($file)) { [IO.File]::Delete($file) }
    }
    [IO.Directory]::Delete($build,$false)
}
Get-Item -LiteralPath $target | Select-Object FullName, Length
