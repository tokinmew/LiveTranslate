@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0.."
if errorlevel 1 exit /b 1
pushd "ocr-tools"
if errorlevel 1 exit /b 1
call Build.cmd
set "helperExit=%errorlevel%"
popd
if not "%helperExit%"=="0" exit /b %helperExit%
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe /platform:x64 /optimize+ /codepage:65001 /win32icon:ui\LiveTranslate.ico /out:LiveTranslate.exe /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll ui\*.cs
if errorlevel 1 exit /b 1
echo Built LiveTranslate.exe
