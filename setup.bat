@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found in PATH. Install Python 3.10+ and re-run.
    exit /b 1
)

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo Done. Make sure ViGEmBus is installed:
echo   https://github.com/nefarius/ViGEmBus/releases
echo.
echo Then run:  run.bat
endlocal
