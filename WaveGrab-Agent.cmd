@echo off
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if exist "%~dp0_internal\agent_cli.py" (
  "%~dp0.runtime\Scripts\python.exe" "%~dp0_internal\agent_cli.py" %*
) else (
  "%~dp0dist\.runtime\Scripts\python.exe" "%~dp0src\agent_cli.py" %*
)
exit /b %errorlevel%
