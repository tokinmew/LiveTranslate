@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 exit /b 1
set "nonInteractive=0"
if /i "%~1"=="--non-interactive" set "nonInteractive=1"
set "setupScript=Setup.ps1"
if exist "payload\" set "setupScript=Prepare-Offline.ps1"
if exist "Prepare-Offline.ps1" set "setupScript=Prepare-Offline.ps1"
if not exist "%setupScript%" (
  echo Setup files are missing. Extract the entire ZIP and open Start.cmd.
  exit /b 1
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0%setupScript%"
set "setupExit=%errorlevel%"
if "%nonInteractive%"=="1" exit /b %setupExit%
if not "%setupExit%"=="0" (
  echo.
  echo Setup did not finish. Read the error above before trying again.
  pause
  exit /b 1
)
echo.
echo Setup finished. Open Start.cmd to use Live Translate.
pause
exit /b 0
