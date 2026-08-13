@echo off
setlocal
title FRLG Auto RNG
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "ENTRY_POINT=%~dp0run_auto_rng_gui.py"
set "LOG_DIR=%~dp0runtime"
set "LOG_FILE=%LOG_DIR%\launcher.log"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
>"%LOG_FILE%" echo [%date% %time%] Starting FRLG Auto RNG...

if not exist "%PYTHON_EXE%" (
    echo Python environment was not found:
    echo   %PYTHON_EXE%
    echo Run the installation BAT in this folder first, then try again.
    >>"%LOG_FILE%" echo ERROR: virtual environment not found.
    pause
    exit /b 1
)

if not exist "%ENTRY_POINT%" (
    echo GUI entry point was not found:
    echo   %ENTRY_POINT%
    >>"%LOG_FILE%" echo ERROR: GUI entry point not found.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -u "%ENTRY_POINT%" 1>>"%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo FRLG Auto RNG failed to start. Exit code: %EXIT_CODE%
    echo Error log: %LOG_FILE%
    echo.
    type "%LOG_FILE%"
    echo.
    pause
)

exit /b %EXIT_CODE%
