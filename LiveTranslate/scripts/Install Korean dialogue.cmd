@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0.."
if errorlevel 1 exit /b 1
echo Optional Korean dialogue - NVIDIA GPU
echo.
echo This setup downloads about 3.53 GB. Allow at least 4.17 GB free
echo plus space for any existing files you are repairing. The CPU models
echo use additional space. An NVIDIA GPU and compatible driver are required.
echo The app will still use its CPU models when the GPU is unavailable.
echo.
echo Read the NVIDIA license before you install. Choose I only if you
echo have read the terms, accept them, and are authorized to do so.
echo.
:choose
"%SystemRoot%\System32\choice.exe" /C TIX /N /M "[T] Read license    [I] Accept and install    [X] Cancel "
if errorlevel 3 exit /b 0
if errorlevel 2 goto install
if errorlevel 1 goto terms
exit /b 1
:terms
start "" "%SystemRoot%\System32\notepad.exe" "dialogue\NVIDIA-License.txt"
goto choose
:install
"runtime\python.exe" -I -B "dialogue\install.py" --online --accept-nvidia-license
set "dialogueResult=%ERRORLEVEL%"
pause
exit /b %dialogueResult%
