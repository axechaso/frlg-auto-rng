@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run_sid_reverse_capture.py
) else (
  python run_sid_reverse_capture.py
)
pause

