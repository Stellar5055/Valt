@echo off
rem Build the one-file valt.exe with PyInstaller.
cd /d "%~dp0"
.venv\Scripts\pyinstaller.exe valt.spec --clean --noconfirm
if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)
echo.
echo Build finished: dist\valt.exe
