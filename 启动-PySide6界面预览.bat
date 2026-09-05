@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo [错误] 找不到 .venv\Scripts\pythonw.exe
  echo 请先创建项目虚拟环境并安装 requirements-pyside-preview.txt
  pause
  exit /b 1
)

".venv\Scripts\pythonw.exe" "%~dp0pyside_preview.py"
if errorlevel 1 (
  echo [错误] PySide6 界面预览启动失败。
  echo 可运行：.venv\Scripts\python.exe -m pip install -r requirements-pyside-preview.txt
  pause
  exit /b 1
)
