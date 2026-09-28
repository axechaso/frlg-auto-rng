@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please run 安装-PySide6源码版.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import PySide6; import pyside_app.window" >nul 2>&1
if errorlevel 1 (
  echo PySide6 source environment is incomplete. Please run 安装-PySide6源码版.bat again.
  pause
  exit /b 1
)
start "FRLG Auto RNG" ".venv\Scripts\pythonw.exe" "run_pyside6_gui.py"
