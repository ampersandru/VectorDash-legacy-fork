@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run Setup-DigUp.cmd once to install the desktop dependencies.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -c "import PySide6.QtWidgets, psutil" >nul 2>&1
if errorlevel 1 (
  echo Desktop dependencies are missing. Run Setup-DigUp.cmd.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0desktop.py"
