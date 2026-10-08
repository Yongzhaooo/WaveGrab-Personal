@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if exist "dist\WaveGrab-Personal.exe" (
    start "" "dist\WaveGrab-Personal.exe"
) else (
    start "" ".venv\Scripts\pythonw.exe" "src\main_gui.py"
)
