@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0.."
if errorlevel 1 exit /b 1
echo Quality speech models for noncommercial use
echo.
echo Downloads about 1.26 GiB from Hugging Face. Each file is checked against its
echo pinned size and SHA-256, then scanned with Microsoft Defender before use.
echo SenseVoiceSmall and Whisper small recognize speech. NLLB-200 is Meta's research
echo translation model for noncommercial use under CC BY-NC 4.0.
echo See quality\MODEL-NOTICES.txt for the source checks and terms.
echo.
if not exist "quality\install.py" goto incomplete
if not exist "runtime\python.exe" goto prepare
if not exist "runtime\ready.txt" goto prepare
goto install
:prepare
echo Preparing the included offline runtime first.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File "%~dp0Prepare-Offline.ps1"
if errorlevel 1 goto failed
:install
if /i "%~1"=="--offline" goto offline
"runtime\python.exe" -I -B "quality\install.py"
goto checked
:offline
"runtime\python.exe" -I -B "quality\install.py" --offline
:checked
if errorlevel 1 goto failed
echo Open LiveTranslate.exe or restart the dashboard to load your checked models.
if /i not "%~2"=="--non-interactive" pause
exit /b 0
:incomplete
echo Extract the whole ZIP, then open this file in the extracted folder.
:failed
if /i not "%~2"=="--non-interactive" pause
exit /b 1
