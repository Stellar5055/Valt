@echo off
rem Build both one-file executables with PyInstaller.
cd /d "%~dp0"
.venv\Scripts\pyinstaller.exe valt.spec --clean --noconfirm
if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)
echo.
echo Build finished:
echo   dist\valt.exe       ^(GUI + CLI^)
echo   dist\valt-cli.exe   ^(CLI only^)
