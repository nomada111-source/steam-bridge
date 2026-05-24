@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtualenv missing. Run setup.bat first.
    exit /b 1
)

call .venv\Scripts\activate.bat

REM Make sure PyInstaller is installed in the venv.
python -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install pyinstaller
)

REM Clean previous build outputs so we don't pick up stale artifacts.
if exist build (rmdir /s /q build)
if exist dist  (rmdir /s /q dist)

echo Building single-file SteamPadBridge.exe...
python -m PyInstaller --clean --noconfirm SteamPadBridge.spec
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo.
echo Done. Output: dist\SteamPadBridge.exe
dir /b dist
endlocal
