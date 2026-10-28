@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" if exist "src\main_gui.py" (
    start "" ".venv\Scripts\pythonw.exe" "src\main_gui.py" --show
    exit /b 0
)
if exist "WaveGrab-Personal.exe" (
    start "" "WaveGrab-Personal.exe" --show
) else if exist "dist\WaveGrab-Personal.exe" (
    start "" "dist\WaveGrab-Personal.exe" --show
)
