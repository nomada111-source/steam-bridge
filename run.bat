@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtualenv missing. Run setup.bat first.
    exit /b 1
)

call .venv\Scripts\activate.bat
python -m src %*
endlocal
