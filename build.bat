@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
.venv\Scripts\python.exe -m PyInstaller --noconfirm build.spec
if errorlevel 1 exit /b 1
echo Built: dist\WaveGrab-Personal.exe
