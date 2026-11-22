$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$OutputEncoding = New-Object Text.UTF8Encoding($false)
$appRoot = [IO.Path]::GetFullPath($PSScriptRoot)
. (Join-Path $appRoot 'Get-CheckedModels.ps1')

function Get-BootstrapArchive([Uri]$Url, [string]$Target, [string]$Digest, [string]$Scanner) {
    if ($Url.Scheme -ne 'https' -or $Url.Port -ne 443 -or $Url.UserInfo -or
        $Url.Host -notin @('www.python.org','files.pythonhosted.org')) {
        throw 'Unexpected runtime download address.'
    }
    if ([IO.File]::Exists($Target) -and (([IO.File]::GetAttributes($Target) -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw 'Runtime cache entries must be ordinary files.'
    }
    if (!([IO.File]::Exists($Target)) -or (Get-FileHash -LiteralPath $Target).Hash -ne $Digest) {
        $temp = Join-Path ([IO.Path]::GetDirectoryName($Target)) ([Guid]::NewGuid().ToString('N') + '.zip')
        try {
            Write-Host ('Downloading ' + [IO.Path]::GetFileName($Target))
            Invoke-WebRequest -Uri $Url -UseBasicParsing -OutFile $temp -MaximumRedirection 0 -TimeoutSec 120
            if ((Get-FileHash -LiteralPath $temp).Hash -ne $Digest) { throw 'Runtime download SHA-256 mismatch.' }
            Move-Item -Force -LiteralPath $temp -Destination $Target
        } finally {
            if ([IO.File]::Exists($temp)) { [IO.File]::Delete($temp) }
        }
    }
    # This lock covers the digest, scan and extraction of both new and cached copies.
    $lock = [IO.File]::Open($Target, 'Open', 'Read', 'Read')
    try {
        if ((Get-FileHash -LiteralPath $Target).Hash -ne $Digest) { throw 'Cached runtime archive changed.' }
        Invoke-FileScan $Scanner $Target
        return $lock
    } catch {
        $lock.Dispose()
        throw
    }
}

$runtimePath = Join-Path $appRoot 'runtime'
$cachePath = Join-Path $appRoot 'setup-cache'
$setupLock = $null
$working = $null
$previous = $null
$promoted = $false
$finished = $false
try {
    if (![Environment]::Is64BitOperatingSystem) { throw 'This build requires 64-bit Windows.' }
    $setupLock = [IO.File]::Open((Join-Path $appRoot 'setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $scanner = Find-Scanner
    Assert-SafeDirectory $cachePath
    if ([IO.Directory]::Exists($runtimePath)) { Assert-SafeDirectory $runtimePath }
    $working = Join-Path $cachePath ('run-' + [Guid]::NewGuid().ToString('N'))
    Assert-SafeDirectory $working
    $bootstrap = Join-Path $working 'runtime'
    Assert-SafeDirectory $bootstrap
    $pythonZip = Join-Path $cachePath 'python-3.13.17-embed-amd64.zip'
    $pipZip = Join-Path $cachePath 'pip-26.2.2.zip'
    $handle = Get-BootstrapArchive 'https://www.python.org/ftp/python/3.13.17/python-3.13.17-embed-amd64.zip' $pythonZip '9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38' $scanner
    try { Expand-Archive -LiteralPath $pythonZip -DestinationPath $bootstrap } finally { $handle.Dispose() }
    $pathFile = Join-Path $bootstrap 'python313._pth'
    @('python313.zip','.','Lib\site-packages') | Set-Content -LiteralPath $pathFile -Encoding ASCII
    $sitePackages = Join-Path $bootstrap 'Lib\site-packages'
    Assert-SafeDirectory $sitePackages
    $handle = Get-BootstrapArchive 'https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl' $pipZip 'fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70' $scanner
    try { Expand-Archive -LiteralPath $pipZip -DestinationPath $sitePackages } finally { $handle.Dispose() }
    $wheelhouse = Join-Path $working 'wheels'
    $pins = Join-Path $working 'checked-wheels.txt'
    Write-Host 'Resolving binary wheels from official PyPI. Each filename, size and digest is checked against its release.'
    & (Join-Path $bootstrap 'python.exe') (Join-Path $appRoot 'backend\runtime_wheels.py') (Join-Path $appRoot 'requirements.txt') $wheelhouse $pins
    if ($LASTEXITCODE -ne 0) { throw 'PyPI download or verification failed. Read the details above and retry setup.' }
    $verifiedFiles = @(Get-ChildItem -LiteralPath $wheelhouse -File -Filter '*.whl')
    if (!$verifiedFiles.Count -or ![IO.File]::Exists($pins)) { throw 'No checked runtime wheels were available.' }
    $locks = New-Object 'Collections.Generic.List[IDisposable]'
    try {
        foreach ($wheel in $verifiedFiles) {
            $lock = [IO.File]::Open($wheel.FullName, 'Open', 'Read', 'Read')
            $locks.Add($lock)
            Invoke-FileScan $scanner $wheel.FullName
            Write-Host ('Defender found no threats in ' + $wheel.Name)
        }
        # Publish the empty bootstrap only after every wheel has passed. Using its
        # permanent path here keeps Windows console launchers valid after setup.
        if ([IO.Directory]::Exists($runtimePath)) {
            $previous = Join-Path $working 'previous-runtime'
            [IO.Directory]::Move($runtimePath, $previous)
        }
        [IO.Directory]::Move($bootstrap, $runtimePath)
        $promoted = $true
        $pythonExe = Join-Path $runtimePath 'python.exe'
        $env:PIP_CONFIG_FILE = 'NUL'
        & $pythonExe -m pip --isolated --no-input --disable-pip-version-check --no-cache-dir install --no-index --no-deps --only-binary=:all: --require-hashes --find-links $wheelhouse -r $pins
        if ($LASTEXITCODE -ne 0) { throw 'The local-only runtime install failed its hash checks or installation.' }
    } finally { foreach ($lock in $locks) { $lock.Dispose() } }
    @('python313.zip','.','Lib\site-packages','..\backend','import site') | Set-Content -LiteralPath (Join-Path $runtimePath 'python313._pth') -Encoding ASCII
    & $pythonExe -m pip --isolated --disable-pip-version-check check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency checks failed.' }
    $runtimeCheck = @'
import struct, sys
assert sys.platform == "win32" and struct.calcsize("P") == 8 and sys.version_info[:3] == (3, 13, 17)
import numpy, scipy, ctranslate2, sentencepiece, faster_whisper, pyaudiowpatch, mss, PIL, pytesseract
from scipy.signal import resample_poly
from py3langid.langid import LanguageIdentifier, MODEL_FILE
from opencc import OpenCC
from tesserocr import PyTessBaseAPI, tesseract_version
identifier = LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)
assert identifier.classify("This is a complete English sentence used to verify the local language detector.")[0] == "en"
assert OpenCC("s2t").convert("\u6c49\u8bed") == "\u6f22\u8a9e"
assert callable(PyTessBaseAPI) and tesseract_version()
assert len(resample_poly(numpy.zeros(480, dtype=numpy.float32), 1, 3)) == 160
'@
    $runtimeCheck | & $pythonExe -
    if ($LASTEXITCODE -ne 0) { throw 'The local translation engine failed its startup check. See the console output above.' }
    foreach ($name in @('backend\worker.py','backend\text_engine.py','backend\audio_engine.py','backend\screen_engine.py')) {
        if (![IO.File]::Exists((Join-Path $appRoot $name))) { throw 'Extract the complete application and retry.' }
    }
    if (![IO.File]::Exists((Join-Path $appRoot 'LiveTranslate.exe'))) {
        & (Join-Path $appRoot 'Build.cmd')
        if ($LASTEXITCODE -ne 0) { throw 'The Windows app could not be compiled.' }
    }
    [IO.File]::Copy($pins, (Join-Path $runtimePath 'checked-runtime-wheels.txt'))
    '0.3' | Set-Content -LiteralPath (Join-Path $runtimePath 'ready.txt') -Encoding ASCII
    $finished = $true
    Write-Host 'Runtime ready. Run Download and test models.cmd to check the language files.'
} catch {
    Write-Host ('Runtime setup stopped: ' + $_.Exception.Message) -ForegroundColor Red
} finally {
    if (!$finished -and $working) {
        try {
            if ($promoted) { [IO.Directory]::Move($runtimePath, (Join-Path $working 'failed-runtime')) }
            if ($previous -and [IO.Directory]::Exists($previous)) { [IO.Directory]::Move($previous, $runtimePath) }
        } catch { Write-Host ('Could not restore the previous runtime. Its setup folder is ' + $working) }
    }
    if ($working -and [IO.Directory]::Exists($working)) {
        # Delete only this setup's own temporary products. Retain any prior runtime.
        $resolvedWork = [IO.Path]::GetFullPath($working)
        if ([IO.Path]::GetDirectoryName($resolvedWork) -eq [IO.Path]::GetFullPath($cachePath) -and
            [IO.Path]::GetFileName($resolvedWork) -match '^run-[0-9a-f]{32}$') {
            foreach ($leaf in @('wheels','runtime','failed-runtime','checked-wheels.txt')) {
                $path = [IO.Path]::GetFullPath((Join-Path $resolvedWork $leaf))
                if ([IO.Path]::GetDirectoryName($path) -ne $resolvedWork) { continue }
                try {
                    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop }
                } catch { Write-Host ('A temporary setup file remains in ' + $working) }
            }
            if ($previous -and [IO.Directory]::Exists($previous)) { Write-Host ('Previous runtime retained in ' + $previous) }
            else { try { [IO.Directory]::Delete($working) } catch { } }
        }
    }
    if ($setupLock) { $setupLock.Dispose() }
}
if (!$finished) { exit 1 }
exit 0
