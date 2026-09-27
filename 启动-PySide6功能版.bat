@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please run 安装-PySide6源码版.bat first.
  pause
  exit /b 1
)
start "FRLG Auto RNG" ".venv\Scripts\pythonw.exe" "run_pyside6_gui.py"
