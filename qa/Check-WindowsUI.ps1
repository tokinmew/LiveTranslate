param([string]$Output = (Join-Path ([IO.Path]::GetTempPath()) ('LiveTranslate-ui-' + [Guid]::NewGuid().ToString('N'))))
$ErrorActionPreference = 'Stop'
$ui = (Get-Item -LiteralPath (Join-Path $PSScriptRoot '../LiveTranslate/ui')).FullName
$sources = (Get-ChildItem -LiteralPath $ui -Filter '*.cs' -File).FullName
$out = [IO.Directory]::CreateDirectory([IO.Path]::GetFullPath($Output)).FullName
$csc = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$references = '/r:System.dll','/r:System.Core.dll','/r:System.Drawing.dll','/r:System.Windows.Forms.dll','/r:System.Web.Extensions.dll'

function Compile([string]$name, [string[]]$arguments) {
    & $csc '/nologo' '/platform:x64' '/codepage:65001' ("/out:$out\$name.exe") @references @arguments
    if ($LASTEXITCODE) { throw "Could not compile $name." }
}

function Run-Check([string]$name, [string]$argument) {
    & (Join-Path $out ($name + '.exe')) $argument
    if ($LASTEXITCODE) { throw "$name failed." }
}

Compile 'LiveTranslate' (@('/target:winexe') + $sources)
$app = Join-Path $out 'LiveTranslate.exe'
foreach ($name in @('CheckRuntimeUI','CheckTranscript')) {
    Compile $name @('/target:exe',(Join-Path $PSScriptRoot ($name + '.cs')))
    Run-Check $name $app
}
Compile 'CheckReplyPractice' @('/target:exe',(Join-Path $PSScriptRoot 'reply-ui/CheckReplyPractice.cs'))
& (Join-Path $out 'CheckReplyPractice.exe') $app (Join-Path $out 'reply-practice.png')
if ($LASTEXITCODE) { throw "CheckReplyPractice failed." }
Compile 'CheckSettings' (@('/target:exe','/main:CheckSettings',(Join-Path $PSScriptRoot 'settings/CheckSettings.cs')) + $sources)
Run-Check 'CheckSettings' $out
Compile 'DashboardCheck' (@('/target:exe','/main:DashboardCheck',(Join-Path $PSScriptRoot 'ui/DashboardCheck.cs')) + $sources)
Run-Check 'DashboardCheck' $out
Compile 'SessionWorkspaceCheck' (@('/target:exe','/main:SessionWorkspaceCheck',(Join-Path $PSScriptRoot 'ui/SessionWorkspaceCheck.cs')) + $sources)
Run-Check 'SessionWorkspaceCheck' $out
Compile 'CheckUpdatesUI' (@('/target:exe','/main:CheckUpdatesUI',(Join-Path $PSScriptRoot 'CheckUpdatesUI.cs')) + $sources)
& (Join-Path $out 'CheckUpdatesUI.exe')
if ($LASTEXITCODE) { throw 'CheckUpdatesUI failed.' }
Compile 'CheckReleaseHistory' (@('/target:exe','/main:CheckReleaseHistory',(Join-Path $PSScriptRoot 'CheckReleaseHistory.cs')) + $sources)
& (Join-Path $out 'CheckReleaseHistory.exe')
if ($LASTEXITCODE) { throw 'CheckReleaseHistory failed.' }
Compile 'OverlayReadabilityChecks' (@('/target:exe','/main:LiveTranslate.OverlayReadabilityChecks',
                                      (Join-Path $PSScriptRoot 'overlays/OverlayReadabilityChecks.cs')) + $sources)
Run-Check 'OverlayReadabilityChecks' $out
Compile 'VrCardControlsChecks' (@('/target:exe','/main:LiveTranslate.VrCardControlsChecks',
                                  (Join-Path $PSScriptRoot 'overlays/VrCardControlsChecks.cs')) + $sources)
Run-Check 'VrCardControlsChecks' $out
foreach ($name in @('ThemedInputChecks','QuietChromeChecks','QuietThemeCheck')) {
    Compile $name (@('/target:exe',('/main:' + $name),(Join-Path $PSScriptRoot ('ui/' + $name + '.cs'))) + $sources)
    Run-Check $name $out
}
Write-Output "Synthetic Windows UI checks passed. Rendered fixtures are in $out"
