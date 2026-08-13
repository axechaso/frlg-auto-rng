@echo off
setlocal
title FRLG Auto RNG Setup
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto verify_venv

set "PYTHON_CMD="
py -3.12 -c "import struct,sys; raise SystemExit(0 if struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3.12"

if defined PYTHON_CMD goto create_venv
python -c "import struct,sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
    echo 64-bit Python 3.12 was not found.
    echo Install Python 3.12 or make the py launcher available, then retry.
    goto error
)

:create_venv
%PYTHON_CMD% -m venv .venv
if errorlevel 1 goto error

:verify_venv
".venv\Scripts\python.exe" -c "import struct,sys; raise SystemExit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 (
    echo The existing .venv is not 64-bit Python 3.12.
    goto error
)

".venv\Scripts\python.exe" -m pip install -r requirements-auto.txt
if errorlevel 1 goto error

".venv\Scripts\python.exe" -c "import cv2,numpy; import rng.tenlines_utils; import automation"
if errorlevel 1 goto error

if exist "local_assets\easycon118\ImgLabel" if exist "local_assets\easycon118\NS火叶SID反查-采集测试.ecs" goto audit_assets
".venv\Scripts\python.exe" tools\import_easycon118.py
if errorlevel 1 goto error
goto assets_ready

:audit_assets
".venv\Scripts\python.exe" tools\audit_easycon118_labels.py local_assets\easycon118\ImgLabel
if not errorlevel 1 goto assets_ready
echo The local 1.1.8 snapshot is older than the required formal/egg package. Re-importing...
".venv\Scripts\python.exe" tools\import_easycon118.py
if errorlevel 1 goto error

:assets_ready
".venv\Scripts\python.exe" tools\prepare_easycon164a.py
if errorlevel 1 goto error

if exist "local_assets\tid_rng137\ImgLabel" (
    ".venv\Scripts\python.exe" tools\import_tid_rng137.py local_assets\tid_rng137 --check-only
    if not errorlevel 1 goto tid_assets_ready
    echo The local TID/SID 1.3.7 snapshot is invalid. Re-importing...
)
".venv\Scripts\python.exe" tools\import_tid_rng137.py
if errorlevel 1 goto error

:tid_assets_ready

if not exist "runtime_backend\easycon164a-cli-gui-rounding-selfcontained\EasyCon2.CLI.exe" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "tools\build_easycon164a_compat_runner.ps1"
    if errorlevel 1 goto error
)
".venv\Scripts\python.exe" -c "from automation import DEFAULT_EZCON_PATH, prepare_compat_runner; print(prepare_compat_runner(DEFAULT_EZCON_PATH))"
if errorlevel 1 goto error

echo.
echo Setup complete. EasyCon 1.6.4a, the GUI-rounding runner, 1.1.8 and TID/SID 1.3.7 are ready.
echo Double-click the launch BAT to start.
pause
exit /b 0

:error
echo.
echo Setup failed. Read the error above for the exact missing component.
pause
exit /b 1
