@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath build\portable build.spec
if errorlevel 1 exit /b 1
if not exist dist mkdir dist
xcopy /E /I /Y "build\portable\WaveGrab-Personal\_internal" "dist\_internal" >nul
if errorlevel 1 exit /b 1
copy /Y "build\portable\WaveGrab-Personal\WaveGrab-Personal.exe" "dist\WaveGrab-Personal.exe" >nul
if errorlevel 1 exit /b 1
echo Built: dist\WaveGrab-Personal.exe
