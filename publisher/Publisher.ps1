$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
function Pick-File($title, $filter) {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    try {
        $dialog.Title = $title
        $dialog.Filter = $filter
        $dialog.InitialDirectory = $PSScriptRoot
        if ($dialog.ShowDialog() -eq 'OK') { return $dialog.FileName }
    } finally { $dialog.Dispose() }
}
try {
    $feed = Join-Path $PSScriptRoot '..\feed\latest.json'
    if (!(Test-Path -LiteralPath $feed -PathType Leaf)) {
        $feed = Join-Path $PSScriptRoot 'feed\latest.json'
    }
    if (!(Test-Path -LiteralPath $feed -PathType Leaf)) {
        $feed = Pick-File 'Choose the release feed manifest' 'LiveTranslate feed manifest (latest.json)|latest.json'
        if (!$feed) { exit 0 }
    }
    $defaultRuntime = Join-Path $env:LOCALAPPDATA 'Programs\LiveTranslate\app\runtime\python.exe'
    if (!(Test-Path -LiteralPath $defaultRuntime -PathType Leaf)) {
        $defaultRuntime = Join-Path $PSScriptRoot '..\LiveTranslate\runtime\python.exe'
    }
    if (Test-Path -LiteralPath $defaultRuntime -PathType Leaf) { $python = $defaultRuntime }
    else {
        $python = Pick-File 'Choose python.exe in your prepared LiveTranslate runtime folder' 'Bundled Python (python.exe)|python.exe'
        if (!$python) { exit 0 }
    }
    $tool = Join-Path $PSScriptRoot 'github_publish.py'
    $dir = Split-Path -Parent $feed
    & $python -I -B -X utf8 $tool --feed $dir --dry-run
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    $meta = Get-Content -LiteralPath $feed -Raw -Encoding UTF8 | ConvertFrom-Json
    $choice = [Windows.Forms.MessageBox]::Show(
        "Publish the tagged source and signed update for version $($meta.version) to private tokinmew/LiveTranslate? This creates the private repository if needed and makes the stable release available to its collaborators.",
        'Publish LiveTranslate update','YesNo','Question','Button2')
    if ($choice -ne 'Yes') { exit 0 }
    & $python -I -B -X utf8 $tool --feed $dir --publish --init-private
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    [void][Windows.Forms.MessageBox]::Show("Verified release v$($meta.version).", 'LiveTranslate publisher')
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
