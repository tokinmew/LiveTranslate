param([Parameter(Mandatory=$true)][string]$File)
$ErrorActionPreference = 'Stop'
# MpCmdRun writes the scanned filename as UTF-8 when stdout is redirected.
# .NET's default stream decoder follows the console's output encoding.
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$modelFile = [IO.Path]::GetFullPath($File)
$kit = [IO.Path]::GetDirectoryName($PSScriptRoot)
. (Join-Path $kit 'scripts\Get-CheckedModels.ps1')
try {
    Invoke-FileScan (Find-Scanner) $modelFile
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
exit 0
