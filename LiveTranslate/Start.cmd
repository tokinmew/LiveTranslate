@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 exit /b 1
if not exist "LiveTranslate.exe" goto incomplete
if not exist "runtime\python.exe" goto prepare
if not exist "runtime\ready.txt" goto prepare
if not exist "model-test-results\offline-43c2c21bc9c17193.ok" goto prepare
for %%L in (zh zt ja ko) do if not exist "data\text-packs\%%L_en\model\model.bin" goto prepare
for %%F in (model.bin config.json tokenizer.json vocabulary.txt) do if not exist "data\speech\base\%%F" goto prepare
for %%L in (chi_sim chi_tra jpn jpn_vert kor) do if not exist "data\tessdata\%%L.traineddata" goto prepare
:launch
start "" "%~dp0LiveTranslate.exe"
exit /b 0
:prepare
echo Preparing the included offline runtime and language models.
echo Please keep this window open. The dashboard opens after the checks pass.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0Prepare-Offline.ps1"
if errorlevel 1 goto failed
goto launch
:incomplete
echo Extract the entire ZIP to a writable folder, then open Start.cmd again.
pause
exit /b 1
:failed
echo Setup stopped. The message above explains what to fix before retrying.
pause
exit /b 1
