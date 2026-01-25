@echo off
echo === Build WASAPI Audio Recorder ===

REM Attiva venv
call venv\Scripts\activate

REM Installa PyInstaller se non presente
pip install pyinstaller --quiet

REM Build exe
pyinstaller build.spec --clean

echo.
echo === Build completato! ===
echo L'eseguibile si trova in: dist\AudioRecorder.exe
pause
