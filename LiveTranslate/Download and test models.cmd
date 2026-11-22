@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HF_HUB_OFFLINE=1"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "interactive=1"
set "scanArg="
set "runtimeAttempted=0"
set "result=0"
pushd "%~dp0" >nul
if errorlevel 1 exit /b 1
:parse
if "%~1"=="" goto check
if /i "%~1"=="--offline" goto useOffline
if /i "%~1"=="--non-interactive" goto noPause
echo Usage: Download and test models.cmd [--offline] [--non-interactive]
set "result=2"
goto finish
:useOffline
set "scanArg=-Offline"
shift
goto parse
:noPause
set "interactive=0"
shift
goto parse
:check
if not exist "model-test-results\" mkdir "model-test-results"
if not exist "model-test-results\" goto unwritable
set "status=model-test-results\last-run.txt"
>"%status%" echo Checking model files. Reports from earlier runs may be stale.
if errorlevel 1 goto unwritable
echo Checking the approved files and scanning them with Microsoft Defender.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0Get-CheckedModels.ps1" %scanArg%
set "result=%errorlevel%"
if not "%result%"=="0" goto blocked
:checkRuntime
if not exist "runtime\python.exe" goto needsRuntime
if not exist "runtime\ready.txt" goto needsRuntime
if not exist "runtime\checked-runtime-wheels.txt" goto needsRuntime
findstr.exe /x /l /c:"0.3" "runtime\ready.txt" >nul
if errorlevel 1 goto needsRuntime
if not exist "backend\verify_reviewed_models.py" goto missingChecker
echo Testing the approved local files.
"runtime\python.exe" -u "backend\verify_reviewed_models.py"
set "result=%errorlevel%"
if not "%result%"=="0" goto testFailed
>"%status%" echo The model files passed verification and the local model test suite completed successfully.
echo Model tests passed. Open model-test-results to read the reports.
goto finish
:testFailed
>"%status%" echo The files passed verification. The latest model test exited with code %result%. Read the current test reports and console output.
echo The model test returned exit code %result%. Review its results in model-test-results.
goto finish
:needsRuntime
if defined scanArg goto offlineRuntime
if "%runtimeAttempted%"=="1" goto failedRuntime
if not exist "Setup.ps1" goto failedRuntime
set "runtimeAttempted=1"
>"%status%" echo All model files passed. Installing and scanning the runtime.
echo Installing the local translation engine and scanning its packages with Defender.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0Setup.ps1"
if errorlevel 1 goto failedRuntime
goto checkRuntime
:failedRuntime
set "result=3"
>"%status%" echo The models passed verification. Runtime setup failed. No inference tests ran.
echo Runtime setup did not finish. Read the setup error above and rerun this tool to retry.
goto finish
:offlineRuntime
set "result=3"
>"%status%" echo The model files passed verification. No engine is ready. No inference tests ran. Previous inference reports are stale.
echo The verified model files are ready. Run Setup.cmd to install the local engine, then rerun this tool with --offline.
goto finish
:missingChecker
set "result=3"
>"%status%" echo The model files passed verification. The offline checker is missing. No inference tests ran.
echo Extract the complete model kit. It must contain backend\verify_reviewed_models.py.
goto finish
:blocked
>"%status%" echo Latest model verification FAILED with exit code %result%. No inference tests ran. Previous inference reports are stale. Review the console and model-file-checks.json.
echo Model verification did not finish successfully. No models were opened for inference.
goto finish
:unwritable
echo Cannot write to model-test-results. Extract this ZIP into a writable folder and retry.
set "result=1"
:finish
popd
if "%interactive%"=="1" pause
exit /b %result%
