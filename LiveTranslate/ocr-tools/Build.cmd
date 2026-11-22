@echo off
setlocal
cd /d "%~dp0"
set "fw=%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319"
set "winmd=%SystemRoot%\System32\WinMetadata"
"%fw%\csc.exe" /nologo /target:exe /platform:x64 /optimize+ /out:EnglishOcr.exe /reference:"%fw%\System.Runtime.dll" /reference:"%fw%\System.Runtime.WindowsRuntime.dll" /reference:"%fw%\System.Runtime.InteropServices.WindowsRuntime.dll" /reference:"%winmd%\Windows.Foundation.winmd" /reference:"%winmd%\Windows.Globalization.winmd" /reference:"%winmd%\Windows.Graphics.winmd" /reference:"%winmd%\Windows.Media.winmd" /reference:"%winmd%\Windows.Storage.winmd" EnglishOcr.cs
exit /b %errorlevel%
