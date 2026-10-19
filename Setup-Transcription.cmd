@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
python -m venv dist\.runtime
if errorlevel 1 exit /b 1
dist\.runtime\Scripts\python.exe -m pip install -r requirements-transcription.txt
if errorlevel 1 exit /b 1
dist\.runtime\Scripts\python.exe src\transcribe_worker.py --models dist\models
if errorlevel 1 exit /b 1
echo Local transcription is ready.
