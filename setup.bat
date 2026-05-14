@echo off
echo === TypeTune Setup ===

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install from https://python.org
    pause
    exit /b 1
)

echo Creating virtual environment...
python -m venv .venv

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt

if not exist "app\songs" mkdir app\songs

echo.
echo === Setup complete ===
echo.
echo Drop your music files (.mp3, .wav, .mid, .ogg, .flac, .m4a) into:
echo   %~dp0app\songs\
echo.
echo To run TypeTune:
echo   .venv\Scripts\activate
echo   python -m app.main
echo.
pause
