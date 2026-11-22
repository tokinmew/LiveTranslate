param(
    [Parameter(Mandatory=$true)][string]$Manifest,
    [Parameter(Mandatory=$true)][string]$KeyFile
)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Security
$path=(Resolve-Path -LiteralPath $Manifest).Path
$manifestData=Get-Content -Raw -LiteralPath $path -Encoding UTF8 | ConvertFrom-Json
$v=[string]$manifestData.version
$expected="LiveTranslate-$v.json"
if($v -cnotmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' -or $manifestData.schema -ne 1 -or $manifestData.product -cne 'LiveTranslate' -or $manifestData.package -cne $expected){throw 'Unexpected manifest for the stable LiveTranslate feed.'}
$asset=Get-Item -LiteralPath (Join-Path (Split-Path $path) $expected)
$digest=(Get-FileHash -Algorithm SHA256 -LiteralPath $asset.FullName).Hash.ToLowerInvariant()
if($asset.Length -ne $manifestData.size -or $asset.Length -le 0 -or $asset.Length -gt 8MB -or $digest -cne $manifestData.sha256){throw 'Package length or digest differs from manifest.'}
$identity=@('LiveTranslate','tokinmew/livetranslate','stable','1',$v,$expected,[string]$asset.Length,$digest)
$payload=[Text.Encoding]::ASCII.GetBytes([string]::Join([char]10,$identity))
$rsa=New-Object Security.Cryptography.RSACryptoServiceProvider
$rsa.PersistKeyInCsp=$false
$raw=$null
$tmp=$path+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
try {
    $raw=[Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $KeyFile).Path),$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
    $rsa.ImportCspBlob($raw)
    if($rsa.KeySize -ne 3072 -or $rsa.PublicOnly){throw 'Expected the dedicated 3072-bit release signer.'}
    $signature=$rsa.SignData($payload,[Security.Cryptography.CryptoConfig]::MapNameToOID('SHA256'))
    $manifestData | Add-Member -Force -NotePropertyName release_signature -NotePropertyValue ([Convert]::ToBase64String($signature))
    [IO.File]::WriteAllText($tmp,($manifestData|ConvertTo-Json -Depth 4 -Compress),[Text.UTF8Encoding]::new($false))
    [IO.File]::Replace($tmp,$path,($path+'.before-signing.bak'))
    Write-Output "Signed LiveTranslate $v stable."
} finally {
    if($raw){[Array]::Clear($raw,0,$raw.Length)}
    if([IO.File]::Exists($tmp)){[IO.File]::Delete($tmp)}
    $rsa.Dispose()
}
